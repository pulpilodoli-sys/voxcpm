"""Optional loopback OpenAI-compatible Transformers server, no remote uploads.

Default small model is for visual transport diagnostics, not Chinese screenplay quality.
Use an appropriate, tested multilingual model for production.
"""
import argparse
import base64
import io
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def decode_messages(messages):
    from PIL import Image
    rendered, images = [], []
    for message in messages:
        content = message['content']
        if isinstance(content, str):
            rendered.append({'role': message['role'], 'content': [{'type': 'text', 'text': content}]})
            continue
        blocks = []
        for block in content:
            if block['type'] == 'text':
                blocks.append(block)
            elif block['type'] == 'image_url':
                url = block['image_url']['url']
                if not url.startswith(('data:image/jpeg;base64,', 'data:image/png;base64,')):
                    raise ValueError('仅支持内嵌 JPEG / PNG，不下载外部图片')
                image = Image.open(io.BytesIO(base64.b64decode(url.split(',', 1)[1], validate=True)))
                if image.width * image.height > 16_000_000 or len(images) >= 24:
                    raise ValueError('图像过大或数量超过 24')
                images.append(image.convert('RGB'))
                blocks.append({'type': 'image'})
            else:
                raise ValueError('不支持的消息类型')
        rendered.append({'role': message['role'], 'content': blocks})
    return rendered, images


def main():
    parser = argparse.ArgumentParser(description='本机 Transformers 视觉接口（可选）')
    parser.add_argument('--model', default='HuggingFaceTB/SmolVLM-256M-Instruct')
    parser.add_argument('--revision', default='main')
    parser.add_argument('--port', type=int, default=11435)
    parser.add_argument('--dtype', choices=['float32', 'bfloat16'], default='float32')
    parser.add_argument('--max-new-tokens', type=int, default=1024)
    args = parser.parse_args()
    import torch
    from transformers import AutoProcessor, AutoModelForImageTextToText
    torch.set_num_threads(4)
    processor = AutoProcessor.from_pretrained(args.model, revision=args.revision, trust_remote_code=False)
    model = AutoModelForImageTextToText.from_pretrained(args.model, revision=args.revision,
                trust_remote_code=False, use_safetensors=True, dtype=getattr(torch, args.dtype),
                attn_implementation='eager').to('cpu').eval()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/v1/models':
                self.reply(200, {'object': 'list', 'data': [{'id': args.model, 'object': 'model'}]})
            else:
                self.reply(404, {'error': 'not found'})

        def do_POST(self):
            if self.path != '/v1/chat/completions':
                self.reply(404, {'error': 'not found'})
                return
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 32 * 1024 * 1024:
                    self.reply(413, {'error': '请求大小必须为 1–32MB'})
                    return
                payload = json.loads(self.rfile.read(length))
                if payload.get('model') != args.model:
                    self.reply(400, {'error': '模型名称与已加载模型不一致'})
                    return
                messages, images = decode_messages(payload['messages'])
                prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
                inputs = processor(text=prompt, images=images or None, return_tensors='pt')
                if inputs['input_ids'].shape[1] > 16000:
                    self.reply(400, {'error': '上下文超过本机服务 16000 token 上限'})
                    return
                temperature = max(0.0, min(2.0, float(payload.get('temperature', 0.2))))
                sampling = {'do_sample': temperature > 0, 'repetition_penalty': 1.1}
                if temperature > 0:
                    sampling.update(temperature=temperature, top_p=0.8, top_k=20)
                with torch.inference_mode():
                    output = model.generate(**inputs, max_new_tokens=min(2048, args.max_new_tokens, max(1, int(payload.get('max_tokens', 1024)))), **sampling)
                text = processor.batch_decode(output[:, inputs['input_ids'].shape[1]:], skip_special_tokens=True)[0]
                eos = model.generation_config.eos_token_id
                eos = eos if isinstance(eos, list) else [eos]
                finish = 'stop' if int(output[0, -1]) in eos else 'length'
                self.reply(200, {'choices': [{'message': {'role': 'assistant', 'content': text}, 'finish_reason': finish}]})
            except Exception as error:
                # Do not echo payloads, keys, signed URLs, or image data in errors.
                self.reply(400, {'error': '本机推理失败：' + type(error).__name__})

        def log_message(self, *unused):
            pass

    print(f'Local model ready on 127.0.0.1:{args.port}; model={args.model}', flush=True)
    HTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
