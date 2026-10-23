"""Use actual HTTP transport and multipart bytes against a deterministic local service."""
import json
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from dramascript.engine import chat, transcribe, process
from tests.helpers import visual_reply


def test_cloud_protocol_and_local_vision_transport(tmp_path):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            seen.append((self.path, dict(self.headers), body))
            result = {'text': '不要打开那封信。'} if self.path.endswith('/transcriptions') else {
                'choices': [{'message': {'content': '人物甲将信收起。'}}]}
            if self.path.endswith('/chat/completions'):
                payload = json.loads(body)
                if payload['messages'][0].get('role') == 'system' and '原始语音文本完整翻译' in payload['messages'][0]['content']:
                    result['choices'][0]['message']['content'] = payload['messages'][1]['content']
                if payload['messages'][0].get('role') == 'system' and 'JSON 对象' in payload['messages'][0]['content']:
                    result['choices'][0]['message']['content'] = visual_reply(payload['messages'], '人物甲将信收起。')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = {'url': f'http://127.0.0.1:{server.server_port}/v1', 'model': 'vision',
                  'audio_model': 'transcribe', 'key': 'test-only-key'}
        audio = tmp_path / 'audio.wav'
        audio.write_bytes(b'RIFF-test-audio')
        assert transcribe(config, audio) == '不要打开那封信。'
        assert seen[0][0] == '/v1/audio/transcriptions'
        assert 'multipart/form-data' in seen[0][1]['Content-Type']
        assert b'RIFF-test-audio' in seen[0][2]
        assert b'name="model"' in seen[0][2]
        assert seen[0][1]['Authorization'] == 'Bearer test-only-key'
        config['key'] = ''  # Local calls must work without cloud authentication.
        message = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,AA=='}}]}]
        assert chat(config, message) == '人物甲将信收起。'
        assert 'Authorization' not in seen[1][1]
        assert json.loads(seen[1][2])['messages'] == message
        assert json.loads(seen[1][2])['max_tokens'] == 2048
        video = tmp_path / 'audio-video.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=160x120:d=1',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-shortest', '-y', str(video)], check=True)
        config.update(mode='云端', key='test-only-key')
        text, data = process(video, tmp_path / 'project', config, lambda *a: None, lambda: False)
        assert data['complete']
        assert data['chunks'][0]['transcript'] == '不要打开那封信。'
        assert '人物甲将信收起。' in text
        assert len(seen) == 5
        assert '不要打开那封信。' == json.loads(seen[3][2])['messages'][1]['content']
        assert '不要打开那封信。' not in str(json.loads(seen[4][2])['messages'])
        assert b'RIFF' in seen[2][2]
        assert b'verbose_json' in seen[2][2]
        assert text.count('不要打开那封信。') == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
