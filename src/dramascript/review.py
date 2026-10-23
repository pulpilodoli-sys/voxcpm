"""Deterministic evidence report with bounded, quoted AI hypotheses."""
import hashlib
import json
from pathlib import Path

from .engine import Cancelled, chat, save, validate_config
from .screenplay import chinese_text
from .storage import project_guard

BUDGET = 18000
TRAITS = {'谨慎', '冲动', '沉着', '急躁', '自信', '犹豫', '坚定', '温和', '强势',
          '关心他人', '重视责任', '善于合作', '警惕', '幽默', '寡言', '外向', '不明'}
ISSUES = {'人物身份待核实', '道具归属待核实', '时间线待核实', '对白归属待核实', '因果关系待核实'}
PROMPT = '''只根据给出的证据卡片，提取待核实线索。只输出 JSON，不写说明或外部知识。
格式：{"characters":[{"name":"未识别声音","trait":"重视责任","evidence_id":"实际卡片ID"}],"issues":[{"kind":"对白归属待核实","evidence_ids":["实际卡片ID"]}]}
姓名只能是所选卡片 text 中实际提及的中文名称，或“未识别声音”。姓名被提及不表示就是该说话人，不能从熟悉台词认定历史人物。
trait 只能选：谨慎、冲动、沉着、急躁、自信、犹豫、坚定、温和、强势、关心他人、重视责任、善于合作、警惕、幽默、寡言、外向、不明。
这些都是言语/行为倾向的候选推断，不是确认性格。无证据就返回空数组，不能猜口音、年龄、真实或虚构身份、历史来源。
issues.kind 只能选人物身份待核实、道具归属待核实、时间线待核实、对白归属待核实、因果关系待核实。不得添加其他字段或长篇解释。'''
def groups(items, budget=BUDGET):
    """Bound request size without silently cutting away evidence."""
    batch, size = [], 0
    for item in items:
        if len(item) > budget:
            # Explicitly partition unusually verbose model output; no truncation.
            if batch:
                yield '\n\n'.join(batch)
                batch, size = [], 0
            for start in range(0, len(item), budget):
                yield '[长证据分段，需结合相邻段]\n' + item[start:start + budget]
            continue
        if batch and size + len(item) + 2 > budget:
            yield '\n\n'.join(batch)
            batch, size = [], 0
        batch.append(item)
        size += len(item) + 2
    if batch:
        yield '\n\n'.join(batch)



def evidence_cards(manifest, revision=None):
    cards = []
    for number, chunk in enumerate(manifest['chunks']):
        if chunk.get('scenes'):
            for index, scene in enumerate(chunk['scenes']):
                cards.append({'id': f'c{number}-s{index}', 'kind': '画面', 'start': scene['start'], 'end': scene['end'],
                    'text': scene['description'] + '；' + '；'.join(a['text'] for a in scene['actions'])})
        else:
            cards.append({'id': f'c{number}-legacy', 'kind': '旧版待核实证据', 'start': chunk['start'], 'end': chunk['end'], 'text': chunk['analysis']})
        for index, line in enumerate(chunk.get('dialogues', [])):
            cards.append({'id': f'c{number}-d{index}', 'kind': '声音（说话人未识别）', 'start': line['start'], 'end': line['end'], 'text': line['translation']})
    if revision:
        for index, part in enumerate(groups([revision], budget=BUDGET//2)):
            cards.append({'id': f'revision{index}', 'kind': '人工修订（不是自动视频事实）', 'start': None, 'end': None, 'text': part})
    return cards


def validate_findings(text, cards):
    if text.strip().startswith('```'):
        import re
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    value = json.loads(text)
    known = {card['id']: card for card in cards}
    if set(value) != {'characters', 'issues'} or not isinstance(value['characters'], list) or not isinstance(value['issues'], list):
        raise ValueError('invalid findings')
    for item in value['characters']:
        resolved = False
        if set(item) == {'name', 'trait'}:
            candidates = [card for card in cards if (item['name'] == '未识别声音' and card['kind'].startswith('声音')) or (item['name'] != '未识别声音' and item['name'] in card['text'])]
            if len(candidates) == 1:
                item['evidence_id'] = candidates[0]['id']
                resolved = True
        if set(item) != {'name', 'trait', 'evidence_id'}:
            raise ValueError('unsupported claims')
        source = known[item['evidence_id']]
        chinese_text(item['name'], '姓名线索')
        if item['name'] == '未识别声音' and not source['kind'].startswith('声音'):
            raise ValueError('voice claim needs audio evidence')
        if item['name'] != '未识别声音' and item['name'] not in source['text']:
            raise ValueError('unmentioned name')
        if item['trait'] not in TRAITS:
            raise ValueError('unsupported trait')
        if resolved:
            item['reference_resolution'] = '唯一证据自动关联，语义和人物归属仍待核实'
    for issue in value['issues']:
        if set(issue) != {'kind', 'evidence_ids'} or issue['kind'] not in ISSUES or not isinstance(issue['evidence_ids'], list) or not issue['evidence_ids']:
            raise ValueError('invalid issue')
        if any(identity not in known for identity in issue['evidence_ids']):
            raise ValueError('unknown evidence')
    return value


def review(project, config, progress, cancelled):
    with project_guard(project):
        return _review(project, config, progress, cancelled)


def _review(project, config, progress, cancelled):
    validate_config(config)
    folder = Path(project)
    manifest = json.loads((folder / 'project.json').read_text(encoding='utf-8'))
    if not manifest['chunks']:
        raise RuntimeError('项目没有已完成片段，请先完成至少一段分析。')
    revision_path = folder / '剧本修订稿.txt'
    revision = revision_path.read_text(encoding='utf-8') if revision_path.exists() else None
    cards = evidence_cards(manifest, revision)
    identity = hashlib.sha256(json.dumps([2, cards, {k: v for k, v in config.items() if k != 'key'}], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    cache_path = folder / 'review-cache.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    if cache.get('identity') != identity:
        cache = {'identity': identity, 'responses': {}}
    # Split only between complete cards, so quote IDs always retain their source.
    batches, batch, size = [], [], 0
    for card in cards:
        length = len(json.dumps(card, ensure_ascii=False))
        if length > BUDGET:
            raise RuntimeError('单条证据过长，请先分段处理。')
        if batch and size + length > BUDGET:
            batches.append(batch)
            batch, size = [], 0
        batch.append(card)
        size += length
    if batch:
        batches.append(batch)
    findings = {'characters': [], 'issues': []}
    failures = []
    for index, batch in enumerate(batches):
        if cancelled():
            raise Cancelled('核对已暂停；已验证的线索缓存可继续复用。')
        progress(int(index / len(batches) * 100), f'核对人物线索 {index+1}/{len(batches)}（时间线由证据直接生成）')
        body = json.dumps(batch, ensure_ascii=False)
        key = hashlib.sha256((PROMPT + body).encode()).hexdigest()
        try:
            response = cache['responses'].get(key)
            if response is None:
                response = chat(config, [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': body}])
            (folder / f'review-response-{index:04d}.txt').write_text(response, encoding='utf-8')
            result = validate_findings(response, batch)
            cache['responses'][key] = response
            save(cache_path, cache)
            for category in ('characters', 'issues'):
                for item in result[category]:
                    if item not in findings[category]:
                        findings[category].append(item)
        except Cancelled:
            raise
        except Exception as error:
            failures.append({'type': type(error).__name__, 'reason': str(error) if isinstance(error, (ValueError, KeyError, TypeError)) else '模型请求或内容校验未成功'})
    known = {card['id']: card for card in cards}

    def source_label(card):
        time = '时间未绑定' if card['start'] is None else f"{card['start']:.2f}–{card['end']:.2f}秒"
        return f"{time} · {card['kind']}：{card['text']}"

    complete = '视频分析已完成' if manifest.get('complete') else '仅覆盖已完成片段，不能当作全片完成'
    parts = ['全片证据核对与待核实人物线索', f'范围：{complete}。以下时间和声音条目由项目证据直接生成，模型不能改写。',
             '一、时间顺序证据清单', *[source_label(card) for card in cards if card['kind'] != '人工修订（不是自动视频事实）'],
             '二、人物档案线索（姓名提及不等于说话人归属；性格倾向仅是推断）']
    for item in findings['characters']:
        parts.append(f"姓名线索：{item['name']}；言语/行为倾向候选：{item['trait']}（待核实）。\n证据由程序原样引用：{source_label(known[item['evidence_id']])}")
        if item.get('reference_resolution'):
            parts.append('引用说明：' + item['reference_resolution'])
    if not findings['characters']:
        parts.append('没有通过引用校验的人物线索。不能据此确认姓名、性格或人物关系。')
    parts.append('三、连续性核对项目（待人工确认，不是已证实矛盾）')
    for issue in findings['issues']:
        parts.append(issue['kind'] + '\n' + '\n'.join(source_label(known[identity]) for identity in issue['evidence_ids']))
    if not findings['issues']:
        parts.append('没有通过引用校验的模型核对项目；不代表剧情不存在问题。')
    parts.extend(['四、已知范围限制', '对白未自动完成声纹与出镜身份匹配；抽样间隙可能有未记录事件；时间先后不能直接证明因果；跨批次关系尚未自动确认。',
                  '本报告不修改剧本正文，不能作为剧情逻辑、人物性格或完整性的自动验收。'])
    if failures:
        parts.append('部分模型线索未通过校验或未成功生成，当前只保留原始证据和已验证的引用；不展示无依据的外部结论。')
    status = {'schema_and_references_validated': not failures, 'semantic_quality_accepted': False,
              'failed_batches': len(failures), 'total_batches': len(batches), 'errors': failures}
    report = '\n\n'.join(parts)
    (folder / '全片审校报告.txt').write_text(report, encoding='utf-8')
    save(folder / 'review-status.json', status)
    progress(100, '证据核对报告已保存；人物线索仍需人工确认。')
    return report, {**manifest, 'review_status': status}
