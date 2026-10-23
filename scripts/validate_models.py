"""Real provider verification, deliberately separate from mocked automated tests.

Run with a representative video. All media/model outputs remain in the chosen project.
No API key is written to the result or printed.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from dramascript.engine import process
from dramascript.review import review


def main():
    parser = argparse.ArgumentParser(description='使用实际模型验证视频 → 中文剧本 → 全片审校')
    parser.add_argument('--mode', choices=['local', 'cloud'], required=True)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--url')
    parser.add_argument('--model')
    parser.add_argument('--audio-model')
    parser.add_argument('--review', action='store_true')
    parser.add_argument('--resume', action='store_true', help='允许复用已有项目缓存；不能据此判断本次重新调用了所有模型')
    args = parser.parse_args()
    if args.project.exists() and any(args.project.iterdir()) and not args.resume:
        parser.error('真实模型新验证需要空目录；继续已有任务请显式添加 --resume，缓存结果不代表本次新推理。')
    local = args.mode == 'local'
    config = {
        'mode': '本地' if local else '云端',
        'url': args.url or ('http://localhost:11434/v1' if local else 'https://api.openai.com/v1'),
        'model': args.model or ('qwen2.5vl:3b' if local else 'gpt-4.1'),
        'audio_model': args.audio_model or ('tiny' if local else 'whisper-1'),
        'key': '' if local else os.environ.get('DRAMASCRIPT_API_KEY', ''),
    }
    started = time.monotonic()
    progress = lambda percent, message: print(f'{percent:3d}% {message}', flush=True)
    try:
        text, data = process(args.video, args.project, config, progress, lambda: False)
        if not text.strip() or not data.get('complete'):
            raise RuntimeError('未生成完整非空草稿')
        if args.review:
            review(args.project, config, progress, lambda: False)
        result = {'provider': args.mode, 'chunks': len(data['chunks']),
                  'elapsed_seconds': round(time.monotonic() - started, 2),
                  'pipeline_completed': True, 'quality_accepted': False, 'cache_reuse_allowed': args.resume,
                  'note': '流程已完成；若允许恢复则可能复用缓存，不代表本次重新调用了每个模型。剧情正确性、完整性和人物身份仍须对照原片人工验收。'}
        (args.project / 'real-validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        # Model/client exceptions can carry signed download URLs; do not echo those.
        print(f'真实联调未完成（{type(error).__name__}）。检查网络域名、模型安装、接口权限及密钥。中间结果已保留。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
