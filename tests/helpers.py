import json
import re


def visual_reply(messages, action='人物甲看向门口。'):
    text = messages[1]['content'][0]['text']
    start, end = re.search(r'区间：([\d.]+)–([\d.]+)秒', text).groups()
    return json.dumps({'scenes': [{'start': float(start), 'end': float(end), 'setting': '内外景不明',
        'location': '地点不明', 'daytime': '时间不明', 'description': '场景环境待核实。', 'actions': [{'time': float(start), 'text': action}], 'evidence_times': [float(start)]}]}, ensure_ascii=False)
