import json

import pytest
from dramascript import review as module
from dramascript.engine import Cancelled


def project(tmp_path):
    data = {'chunks': [{'start': 0, 'end': 120, 'analysis': '小林藏起信件，身份待核实',
                        'transcript': '明天见', 'script': '内景 房间 日\n小林藏起信件。'}]}
    (tmp_path / 'project.json').write_text(json.dumps(data), encoding='utf-8')
    return data


def test_review_preserves_revision_and_caches(tmp_path, monkeypatch):
    data = project(tmp_path)
    revision = tmp_path / '剧本修订稿.txt'
    revision.write_text('用户亲自修订的内容', encoding='utf-8')
    requests = []

    def fake(config, messages):
        requests.append(messages)
        return json.dumps({'characters': [{'name': '小林', 'trait': '谨慎', 'evidence_id': 'c0-legacy'}], 'issues': []}, ensure_ascii=False)

    monkeypatch.setattr(module, 'chat', fake)
    config = {'mode': '本地', 'url': 'http://localhost:11434/v1', 'model': 'model', 'key': 'never-persist'}
    result, _ = module.review(tmp_path, config, lambda *a: None, lambda: False)
    assert '人物档案' in result
    assert '用户亲自修订' in requests[0][1]['content']
    assert revision.read_text(encoding='utf-8') == '用户亲自修订的内容'
    assert json.loads((tmp_path / 'project.json').read_text()) == data
    assert 'never-persist' not in (tmp_path / 'review-cache.json').read_text()
    module.review(tmp_path, config, lambda *a: None, lambda: False)
    assert len(requests) == 1
    revision.write_text('新的修订', encoding='utf-8')
    module.review(tmp_path, config, lambda *a: None, lambda: False)
    assert len(requests) == 2


def test_review_cancel_and_no_evidence(tmp_path):
    project(tmp_path)
    with pytest.raises(Cancelled):
        module.review(tmp_path, {'mode': '本地', 'url': 'http://localhost:11434/v1'}, lambda *a: None, lambda: True)
    (tmp_path / 'project.json').write_text('{"chunks": []}')
    with pytest.raises(RuntimeError, match='没有已完成'):
        module.review(tmp_path, {'mode': '本地', 'url': 'http://localhost:11434/v1'}, lambda *a: None, lambda: False)


def test_groups_keep_every_character():
    items = ['a' * 100, 'b' * 200, 'c' * 50]
    result = list(module.groups(items, budget=150))
    combined = ''.join(result)
    for char, count in [('a', 100), ('b', 200), ('c', 50)]:
        assert combined.count(char) == count


def test_unsupported_historical_identity_is_not_rendered(tmp_path, monkeypatch):
    project(tmp_path)
    monkeypatch.setattr(module, 'chat', lambda *a: json.dumps({'characters': [{'name': '肯尼迪', 'trait': '重视责任', 'evidence_id': 'c0-legacy'}], 'issues': []}))
    report, data = module.review(tmp_path, {'mode': '本地', 'url': 'http://localhost:11434/v1'}, lambda *a: None, lambda: False)
    assert '肯尼迪' not in report
    assert not data['review_status']['schema_and_references_validated']
    assert '未通过校验' in report
    assert '小林藏起信件' in report


def test_report_keeps_voice_and_seconds_without_model_rewrite(tmp_path, monkeypatch):
    data = project(tmp_path)
    data['complete'] = True
    data['chunks'][0]['dialogues'] = [{'start': 0, 'end': 11, 'translation': '不要开门。'}]
    (tmp_path / 'project.json').write_text(json.dumps(data))
    monkeypatch.setattr(module, 'chat', lambda *a: '{"characters": [], "issues": []}')
    report, result = module.review(tmp_path, {'mode': '本地', 'url': 'http://localhost:11434/v1'}, lambda *a: None, lambda: False)
    assert '0.00–11.00秒' in report and '不要开门。' in report
    assert result['review_status']['schema_and_references_validated']


def test_missing_reference_only_resolved_when_source_is_unique():
    cards = [{'id': 'voice1', 'kind': '声音（说话人未识别）', 'text': '不要问国家能为你做什么。'}]
    response = '{"characters":[{"name":"未识别声音","trait":"重视责任"}],"issues":[]}'
    result = module.validate_findings(response, cards)
    assert result['characters'][0]['evidence_id'] == 'voice1'
    assert '待核实' in result['characters'][0]['reference_resolution']
    cards.append({'id': 'voice2', 'kind': '声音（说话人未识别）', 'text': '另一句。'})
    with pytest.raises(ValueError):
        module.validate_findings(response, cards)
