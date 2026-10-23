"""Validate independent visual/voice evidence and render without rewriting dialogue."""
import json
import re


def chinese_text(text, label):
    if not isinstance(text, str) or not re.search(r'[\u3400-\u9fff]', text):
        raise RuntimeError(f'{label}不是有效中文，当前片段不标记完成。')
    if re.search(r'\b[A-Za-z]{2,}(?:[\s,;.!?]+[A-Za-z]{2,}){3,}\b', text):
        raise RuntimeError(f'{label}仍包含未翻译的外语句子，当前片段不标记完成。')
    return text.strip()


def speech_segments(transcript, start, end):
    if not transcript.strip() or transcript == '[无音轨]':
        return []
    lines = transcript.strip().splitlines()
    result = []
    for line in lines:
        match = re.match(r'^\[([\d.]+)[–-]([\d.]+)秒\]\s*(.*)$', line)
        if match:
            left, right, source = float(match[1]), float(match[2]), match[3]
            if not start <= left <= right <= end + 0.5:
                raise RuntimeError('语音时间范围异常，请核对转写。')
            result.append({'start': left, 'end': min(right, end), 'source': source, 'approximate': False})
        else:
            result.append({'start': start, 'end': end, 'source': line, 'approximate': True})
    return [s for s in result if s['source'].strip()]


def parse_scenes(text, start, end, sample_times):
    if text.strip().startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    try:
        value = json.loads(text)
        scenes = value['scenes']
        if not isinstance(scenes, list) or not scenes:
            raise ValueError('empty scenes')
        if len(scenes) == 1 and 'evidence_times' not in scenes[0] and 'evidence_times' in value:
            # One scene makes document-level references unambiguous; never fabricate them.
            scenes[0]['evidence_times'] = value['evidence_times']
        previous = start
        for scene in scenes:
            left, right = scene['start'], scene['end']
            if isinstance(left, bool) or isinstance(right, bool) or not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
                raise ValueError('invalid time')
            if abs(left - previous) > 0.5 or not start <= left < right <= end + 0.01:
                raise ValueError('overlap or gap')
            if scene['setting'] not in ('内景', '外景', '内外景不明') or scene['daytime'] not in ('日', '夜', '时间不明'):
                raise ValueError('invalid scene metadata')
            chinese_text(scene['location'], '场景地点')
            chinese_text(scene['description'], '静态画面描述')
            if not isinstance(scene['actions'], list):
                raise ValueError('invalid actions')
            for action in scene['actions']:
                chinese_text(action['text'], '画面动作')
                if not isinstance(action['time'], (int, float)) or not left <= action['time'] <= right:
                    raise ValueError('invalid action time')
            evidence = scene['evidence_times']
            if not isinstance(evidence, list) or not evidence or any(
                not isinstance(t, (int, float)) or not left <= t <= right or not any(abs(t - s) < 0.1 for s in sample_times) for t in evidence):
                raise ValueError('unknown evidence time')
            if any(not any(abs(action['time'] - t) < 0.1 for t in evidence) for action in scene['actions']):
                raise ValueError('action lacks frame evidence')
            previous = right
        if abs(previous - end) > 0.5:
            raise ValueError('missing final interval')
        return scenes
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError('画面模型未返回有效场景证据（时间、中文动作或证据引用缺失），请检查模型输出。') from error


def render(scenes, dialogues, offset=0):
    """Each accepted translated utterance is emitted exactly once, never paraphrased."""
    paragraphs = []
    assigned = set()
    for index, scene in enumerate(scenes):
        paragraphs.append(f'第{offset + index + 1}场　{scene["setting"]} · {scene["location"]} · {scene["daytime"]}')
        paragraphs.append(scene['description'])
        events = [(action['time'], 0, action['text']) for action in scene['actions']]
        for number, line in enumerate(dialogues):
            if number not in assigned and (line['start'] < scene['end'] or index == len(scenes)-1):
                label = '未识别声音（说话人及画内外位置待核实）'
                if line.get('approximate'):
                    label += '【场景内时间位置待核实】'
                events.append((line['start'], 1, label + '：' + line['translation']))
                assigned.add(number)
        paragraphs.extend(event[2] for event in sorted(events, key=lambda event: (event[0], event[1])))
    if len(assigned) != len(dialogues):
        raise RuntimeError('存在未安排的声音证据，停止生成以免漏对白。')
    return '\n\n'.join(paragraphs)
