import json
import pytest
from dramascript.screenplay import chinese_text, parse_scenes, render, speech_segments


def scenes():
    return [{'start': 0, 'end': 10, 'setting': '内景', 'location': '客厅', 'daytime': '日', 'description': '客厅里有一扇门。', 'actions': [{'time': 0, 'text': '门打开。'}], 'evidence_times': [0]},
            {'start': 10, 'end': 20, 'setting': '外景', 'location': '街道', 'daytime': '日', 'description': '街道上可见人物甲。', 'actions': [{'time': 10, 'text': '人物甲走上街道。'}], 'evidence_times': [10]}]


def test_translated_speech_preserved_once_across_scene_change():
    lines = [{'start': 2, 'translation': '不要开门。'}, {'start': 11, 'translation': '明天见。'}]
    text = render(scenes(), lines, offset=3)
    assert text.count('不要开门。') == 1 and text.count('明天见。') == 1
    assert text.index('不要开门。') < text.index('第5场') < text.index('明天见。')


def test_untranslated_quote_inside_chinese_is_rejected():
    with pytest.raises(RuntimeError, match='未翻译'):
        chinese_text('对白：Ask not what your country can do for you.', '对白')


@pytest.mark.parametrize('field,value', [('start', 5), ('end', 99), ('evidence_times', [8]), ('actions', [{'time': 0, 'text': 'A man opens the door.'}])])
def test_invalid_scene_evidence_is_not_silently_accepted(field, value):
    items = scenes()
    items[0][field] = value
    with pytest.raises(RuntimeError):
        parse_scenes(json.dumps({'scenes': items}), 0, 20, [0, 10])


def test_timestamped_and_unknown_timing_speech():
    lines = speech_segments('[120.1–121.5秒] Hello.', 120, 130)
    assert not lines[0]['approximate'] and lines[0]['source'] == 'Hello.'
    assert speech_segments('Hello.', 120, 130)[0]['approximate']
    assert speech_segments('[无音轨]', 0, 5) == []


def test_static_scene_without_actions_is_valid():
    scene = scenes()[0]
    scene['actions'] = []
    result = parse_scenes(json.dumps({'scenes': [scene]}), 0, 10, [0])
    assert '客厅里有一扇门。' in render(result, [])


def test_speech_precedes_later_door_action():
    scene = scenes()[0]
    scene['actions'] = [{'time': 8, 'text': '门打开。'}]
    text = render([scene], [{'start': 2, 'translation': '不要开门。'}])
    assert text.index('不要开门。') < text.index('门打开。')


def test_single_scene_can_reference_document_level_frame_evidence():
    scene = scenes()[0]
    del scene['evidence_times']
    payload = {'scenes': [scene], 'evidence_times': [0]}
    assert parse_scenes(json.dumps(payload), 0, 10, [0])[0]['evidence_times'] == [0]
    payload['evidence_times'] = [8]
    with pytest.raises(RuntimeError):
        parse_scenes(json.dumps(payload), 0, 10, [0])


def test_scene_cannot_reference_a_frame_from_another_scene():
    items = scenes()
    items[0]['evidence_times'] = [20]
    with pytest.raises(RuntimeError):
        parse_scenes(json.dumps({'scenes': items}), 0, 20, [0, 10, 20])
