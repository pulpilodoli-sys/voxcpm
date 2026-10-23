"""Incremental, evidence-grounded video analysis. API keys never go into projects."""
import base64
import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from .screenplay import chinese_text, speech_segments, parse_scenes, render
from .storage import project_guard
from .runtime import media_tool, run_media


PIPELINE_VERSION = 4


class Cancelled(Exception):
    pass


def command(args):
    p = run_media(args, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-2500:])
    return p.stdout


def request(url, body, key='', content_type='application/json'):
    headers = {'Content-Type': content_type}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'模型接口 HTTP {e.code}：请检查模型、权限、额度和接口地址。') from None


def validate_config(config):
    url = urlsplit(config.get('url', ''))
    if url.username or url.password or url.query or url.fragment or not url.hostname:
        raise RuntimeError('接口地址不能包含账号、密码、查询参数或片段；密钥应填写在专用输入框。')
    loopback = url.hostname in ('localhost', '127.0.0.1', '::1')
    if url.scheme != 'https' and not (url.scheme == 'http' and loopback):
        raise RuntimeError('远程接口必须使用 HTTPS。')
    if config.get('mode') == '本地' and not loopback:
        raise RuntimeError('本地模式只连接本机服务；远程接口请使用云端模式。')
    if config.get('mode') == '云端' and not config.get('key'):
        raise RuntimeError('请输入云端 API 密钥（仅保存在进程内存）')


def chat(config, messages):
    result = request(config['url'].rstrip('/') + '/chat/completions', json.dumps({
        'model': config['model'], 'messages': messages, 'temperature': 0.2, 'max_tokens': config.get('max_tokens', 2048)
    }).encode(), config.get('key', ''))
    choice = result['choices'][0]
    if choice.get('finish_reason') == 'length':
        raise RuntimeError('模型输出达到长度上限，当前结果不完整；请提高服务输出上限或更换模型后重试。')
    text = choice['message']['content']
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError('模型返回空文本')
    return text


def require_chinese(text, label):
    if not re.search(r'[\u3400-\u9fff]', text):
        raise RuntimeError(f'{label}未包含中文；请选择支持中文的模型后重试。当前片段未标记完成。')
    return text


def transcribe(config, path, offset=0):
    boundary = 'DramaScriptBoundary'
    body = f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{config["audio_model"]}\r\n'.encode()
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="response_format"\r\n\r\nverbose_json\r\n'.encode()
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
    body += path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    result = request(config['url'].rstrip('/') + '/audio/transcriptions', body, config.get('key', ''),
                   f'multipart/form-data; boundary={boundary}')
    if result.get('segments'):
        return '\n'.join(f"[{offset + part['start']:.2f}–{offset + part['end']:.2f}秒] {part['text']}" for part in result['segments'])
    return result['text']


def save(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


TRANSLATE = '将用户提供的原始语音文本完整翻译为简体中文，只返回译文。不要补充人物、场景、文字上屏、解释或新事件；人名译为中文或保留短名称。不要照抄整句外语。'
ANALYZE = '''你是影视画面记录员，只记录抽样图片能直接支持的场景和动作。你没有收到音频，不能断言有无对白，不能凭空生成文字上屏、角色台词、性格或心理。
只输出一个 JSON 对象，不写说明。格式：
{"scenes":[{"start":0,"end":12,"setting":"内外景不明","location":"地点不明","daytime":"时间不明","description":"实际可见环境的中文描述","actions":[{"time":0,"text":"实际可见动作"}],"evidence_times":[0]}]}
start/end 必须使用用户给出的全片秒数，按顺序连续覆盖当前区间。只在图片支持场景切换时分场。边界是抽样估计，不能编造未观察的事件。
setting 只能为内景/外景/内外景不明；daytime 只能为日/夜/时间不明。不明确时不要猜。description 写实际可见环境或静态画面。actions 仅记录实际可见动作及其对应抽样秒数，静态画面允许空数组，不要为了填数组编造动作。动作 time 必须引用同场景 evidence_times 中的时间。不写分镜或机位。evidence_times 必须引用实际给出的抽样秒数。相同画面合并，不重复复述。'''


def process(video, project, config, progress, cancelled):
    with project_guard(project):
        return _process(video, project, config, progress, cancelled)


def _process(video, project, config, progress, cancelled):
    video, project = Path(video), Path(project)
    for tool in ('ffmpeg', 'ffprobe'):
        media_tool(tool)
    validate_config(config)
    public = {k: v for k, v in config.items() if k != 'key'}
    stat = video.stat()
    identity = hashlib.sha256(json.dumps([PIPELINE_VERSION, str(video.resolve()), stat.st_size, stat.st_mtime_ns, public], sort_keys=True).encode()).hexdigest()
    project.mkdir(parents=True, exist_ok=True)
    path = project / 'project.json'
    if not path.exists() and any(p.name != '.dramascript.lock' for p in project.iterdir()):
        raise RuntimeError('新项目请选择空文件夹；当前目录已有文件，程序不会覆盖。')
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
        'identity': identity, 'pipeline_version': PIPELINE_VERSION, 'video': str(video.resolve()), 'config': public, 'chunks': []}
    if data['identity'] != identity:
        raise RuntimeError('项目视频、模型设置或分析流程版本已改变，请选择新的项目文件夹；旧结果保留。')
    save(path, data)
    probe = json.loads(command(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(video)]))
    if not any(s['codec_type'] == 'video' for s in probe['streams']):
        raise RuntimeError('文件没有视频轨道')
    duration = float(probe['format']['duration'])
    audio_present = any(s['codec_type'] == 'audio' for s in probe['streams'])
    total = math.ceil(duration / 120)
    state, previous, whisper = '无前文', '', None
    for i in range(total):
        if cancelled():
            raise Cancelled('已暂停；已完成片段保留，继续时复用。')
        if i < len(data['chunks']):
            state = json.dumps(data['chunks'][i]['scenes'], ensure_ascii=False)
            continue
        start, length = i * 120, min(120, duration - i * 120)
        progress(int(i / total * 100), f'分析第 {i+1}/{total} 段（{start} 秒起）')
        folder = project / f'chunk-{i:05d}'
        folder.mkdir(exist_ok=True)
        for pattern in ('frame-[0-9][0-9][0-9][0-9].jpg', 'scene-[0-9][0-9][0-9][0-9].jpg'):
            for old in folder.glob(pattern):
                old.unlink()
        base = ['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-i', str(video), '-t', str(length)]
        command(base + ['-vf', 'fps=1/10:start_time=0,scale=768:-2,format=yuvj420p', '-q:v', '4', str(folder / 'frame-%04d.jpg')])
        scene_result = run_media(base + ['-loglevel', 'info', '-vf',
            "select='gt(scene,0.35)',showinfo,scale=768:-2,format=yuvj420p",
            '-fps_mode', 'vfr', '-frames:v', '12', str(folder / 'scene-%04d.jpg')],
            capture_output=True, text=True)
        if scene_result.returncode:
            raise RuntimeError(scene_result.stderr[-2500:])
        scene_times = [float(t) for t in re.findall(r'pts_time:([-0-9.]+)', scene_result.stderr)]
        if not list(folder.glob('frame-*.jpg')):
            command(base + ['-frames:v', '1', '-vf', 'scale=768:-2,format=yuvj420p', str(folder / 'frame-0001.jpg')])
        samples = [{'file': p.name, 'time': start + (int(p.stem.split('-')[1])-1)*10,
                    'approximate': True} for p in sorted(folder.glob('frame-*.jpg'))]
        for p, local_time in zip(sorted(folder.glob('scene-*.jpg')), scene_times):
            samples.append({'file': p.name, 'time': start + local_time, 'approximate': False})
        samples.sort(key=lambda sample: sample['time'])
        save(folder / 'frames.json', samples)
        transcript = '[无音轨]'
        if audio_present:
            audio = folder / 'audio.wav'
            command(base + ['-vn', '-ar', '16000', '-ac', '1', str(audio)])
            if config['mode'] == '本地':
                if whisper is None:
                    try:
                        from faster_whisper import WhisperModel
                    except ImportError:
                        raise RuntimeError('本地转写依赖未安装：pip install -e ".[local]"') from None
                    whisper = WhisperModel(config['audio_model'], device='cpu', compute_type='int8')
                segments, _ = whisper.transcribe(str(audio), vad_filter=True)
                transcript = '\n'.join(f'[{start+s.start:.1f}–{start+s.end:.1f}秒] {s.text}' for s in segments)
            else:
                transcript = transcribe(config, audio, start)
        if cancelled():
            raise Cancelled('已暂停；当前未完成片段将在继续时重做。')
        progress(int(i / total * 100), f'第 {i+1}/{total} 段：独立翻译声音')
        dialogues = speech_segments(transcript, start, start + length)
        translation_path = folder / 'translations.json'
        translations = json.loads(translation_path.read_text(encoding='utf-8')) if translation_path.exists() else []
        for number, line in enumerate(dialogues):
            if cancelled():
                raise Cancelled('翻译已暂停，完成的语句已缓存。')
            if number < len(translations) and translations[number]['source'] == line['source']:
                line['translation'] = chinese_text(translations[number]['translation'], '对白译文')
            else:
                line['translation'] = chinese_text(chat(config, [{'role': 'system', 'content': TRANSLATE},
                    {'role': 'user', 'content': line['source']}]), '对白译文')
                translations = dialogues[:number+1]
                save(translation_path, translations)
        progress(int(i / total * 100), f'第 {i+1}/{total} 段：仅识别可见场景')
        content = [{'type': 'text', 'text': f'区间：{start}–{start+length}秒。有效抽样时间：{[sample["time"] for sample in samples]}。此前场景状态仅供身份连续参考：{state}。不要从此前状态推测本段看不见的动作。'}]
        seen_images = {}
        for sample in samples:
            frame = folder / sample['file']
            image_bytes = frame.read_bytes()
            digest = hashlib.sha256(image_bytes).hexdigest()
            if digest in seen_images:
                content.append({'type': 'text', 'text': f"{sample['time']:.2f}秒的抽样画面与{seen_images[digest]:.2f}秒重复；采样间隙内容未知。"})
                continue
            seen_images[digest] = sample['time']
            label = ('约' if sample['approximate'] else '场景变化帧：') + f"{sample['time']:.2f}秒"
            content.extend([{'type': 'text', 'text': label}, {'type': 'image_url', 'image_url': {
                'url': 'data:image/jpeg;base64,' + base64.b64encode(image_bytes).decode()}}])
        visual_path = folder / 'visual-response.txt'
        scenes = None
        if visual_path.exists():
            try:
                scenes = parse_scenes(visual_path.read_text(encoding='utf-8'), start, start + length, [sample['time'] for sample in samples])
            except RuntimeError:
                content.append({'type': 'text', 'text': '上次格式校验失败：请严格包含每个场景的 description、actions 和 evidence_times 字段，不返回未知采样时间。'})
        if scenes is None:
            visual = chat(config, [{'role': 'system', 'content': ANALYZE}, {'role': 'user', 'content': content}])
            visual_path.write_text(visual, encoding='utf-8')
            scenes = parse_scenes(visual, start, start + length, [sample['time'] for sample in samples])
        offset = sum(len(chunk.get('scenes', [{}])) for chunk in data['chunks'])
        script = render(scenes, dialogues, offset)
        analysis = '\n\n'.join(f"场景 {scene['start']}–{scene['end']}秒：{scene['location']}；" + scene['description'] + '；'.join(action['text'] for action in scene['actions']) for scene in scenes)
        analysis += '\n\n独立声音译文（声音身份尚未核实）：\n' + '\n'.join(f"[{line['start']}–{line['end']}秒] {line['translation']}" for line in dialogues)
        data['chunks'].append({'start': start, 'end': start+length, 'transcript': transcript,
            'analysis': analysis, 'script': script, 'samples': samples, 'scenes': scenes, 'dialogues': dialogues})
        data['duration'] = duration
        data['complete'] = i + 1 == total
        save(path, data)
        state = json.dumps(scenes, ensure_ascii=False)
        (project / '剧本草稿.txt').write_text('\n\n'.join(c['script'] for c in data['chunks']), encoding='utf-8')
        progress(int((i+1)/total*100), f'已保存第 {i+1}/{total} 段')
    return '\n\n'.join(c['script'] for c in data['chunks']), data
