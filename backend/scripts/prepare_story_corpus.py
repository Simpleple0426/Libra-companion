"""Reproducible extraction of user-supplied story transcriptions, not a scraper.

Only explicit reviewed selections become approved; mechanical windows stay draft.
No database writes here. Original markdown is never modified.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from domains.persona.character_corpus import validate_sample

SPEAKER = re.compile(r'^\s*(?:\*\*)?([^：:]{1,16})[：:](.*)$')
BOUNDARY = '剧情证据不是现实共同经历。不得据此假定婚姻、同居或身体接触许可，不得声称已送物、接送或完成其他未执行行动。'
CONFIRMED_MONOLOGUES = {'libra/卡面/相守篇/mr梦迟.md': '用户明确确认：全文正文均为左然独白'}


def parse_lines(text, confirmed_monologue=False):
    result, section = [], []
    for number, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith('#'):
            depth = len(raw.lstrip()) - len(raw.lstrip().lstrip('#'))
            section = section[:depth - 1] + [raw.lstrip('# ').strip()]
        match = SPEAKER.match(raw)
        speaker = match.group(1).strip() if match else None
        confirmed = confirmed_monologue and not match and bool(raw.strip()) and not raw.lstrip().startswith('#')
        if confirmed:
            speaker = '左然'
        role = {'我': 'user', '左然': 'libra'}.get(speaker, 'other' if speaker else 'narration_or_unattributed')
        result.append(dict(line=number, raw=raw, speaker=speaker, role=role,
                           text=match.group(2) if match else raw, section=' / '.join(section),
                           attribution='user_confirmed_monologue' if confirmed else 'explicit_label' if match else 'unattributed'))
    return result


def source_ref(path, lines, start, end, digest):
    return dict(work='用户提供的游戏剧情转录', location=f'{path}:L{start}-L{end}',
                path=path, line_start=start, line_end=end, sha256=digest,
                speaker_confirmation=CONFIRMED_MONOLOGUES.get(path),
                section=lines[start - 1]['section'], verification='checked_against_local_transcription_not_official_release')


def record(identifier, ref, context, quote, logic, preferred, avoid, domain, status, stage):
    return validate_sample(dict(id=identifier, domain=domain, type='contextual_character_evidence',
        source_level='explicit_canon', source_ref=ref, context=context,
        character_logic=logic, preferred_direction=preferred,
        avoid_direction=avoid + [BOUNDARY], confidence=.9 if status == 'approved' else .4,
        review_status=status, version=1, example_output=quote,
        applicability={'relationship_stage': stage, 'current_evidence_required': True,
                       'not_a_runtime_script': True},
        review_method='assistant_context_review' if status == 'approved' else 'mechanical_extraction_pending_review'))


def write_jsonl(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in items), encoding='utf-8')


def load_selections(path):
    path = Path(path)
    selections = json.loads(path.read_text(encoding='utf-8'))
    for batch in sorted(path.parent.glob('behavior_*.json')):
        selections.extend(json.loads(batch.read_text(encoding='utf-8')))
    return selections


def prepare(repo, output, selections):
    repo, output = Path(repo).resolve(), Path(output).resolve()
    library = repo / 'libra'
    files = sorted([*(library / '个人线').rglob('*.md'), *(library / '卡面').rglob('*.md')])
    sources, manifest, drafts, approved = {}, [], [], []
    progress_file = library / 'zuoran_corpus_v2' / 'review_progress.json'
    reviews = json.loads(progress_file.read_text(encoding='utf-8')) if progress_file.exists() else []
    review_by_path = {r['path']: r for r in reviews}
    for path in files:
        relative = path.relative_to(repo).as_posix()
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        lines = parse_lines(content.decode('utf-8-sig'), relative in CONFIRMED_MONOLOGUES)
        sources[relative] = (lines, digest)
        review = review_by_path.get(relative)
        if review and (review['sha256'] != digest or review['lines'] != len(lines)):
            raise ValueError('review_source_changed:' + relative)
        key = hashlib.sha256(relative.encode()).hexdigest()[:12]
        write_jsonl(output / 'raw' / (key + '.jsonl'), lines)
        anchors = [line for line in lines if line['role'] == 'libra']
        manifest.append(dict(path=relative, sha256=digest, lines=len(lines),
            libra_lines=len(anchors), user_lines=sum(l['role'] == 'user' for l in lines),
            status='empty' if not content else 'unattributed' if not anchors else 'extracted',
            speaker_confirmation=CONFIRMED_MONOLOGUES.get(relative),
            raw_file='raw/' + key + '.jsonl'))
        manifest[-1]['review_status'] = 'empty_no_content' if not content else 'full_text_reviewed' if review else 'selected_excerpts_only'
        for line in anchors:
            number = line['line']
            start, end = max(1, number - 4), min(len(lines), number + 4)
            ref = source_ref(relative, lines, start, end, digest)
            context = '\n'.join(l['raw'] for l in lines[start - 1:end])
            candidate = record(f'story_{key}_{number}', ref, context, line['text'],
                '此行依据明确标签或用户对该文件的确认归属于左然；受话人、情境完整性与可迁移倾向尚待审核。',
                ['审核完整场景后再提炼条件性倾向'], ['不可直接进入运行时检索'],
                'dialogue', 'draft', 'unknown')
            if review:
                candidate.update(review_status='reviewed', review_method='full_text_scene_review',
                    character_logic='该文件已完成逐场景审核；此窗口仅保留原文索引，行为结论见正式情境条目。',
                    review_disposition='source_index_only_not_runtime_evidence')
                if any(a <= number <= b for a, b in review.get('quotation_spans', [])):
                    candidate['utterance_kind'] = 'quotation_or_recalled_speech_not_new_character_position'
            drafts.append(candidate)
    for selection in selections:
        lines, digest = sources[selection['path']]
        matches = [l for l in lines if l['role'] == 'libra' and selection['anchor'] in l['text']]
        if 'anchor_line' in selection:
            matches = [l for l in matches if l['line'] == selection['anchor_line']]
        if len(matches) != 1:
            raise ValueError(f"ambiguous_or_missing_anchor:{selection['id']}")
        line = matches[0]
        start, end = selection['span']
        if not 1 <= start <= line['line'] <= end <= len(lines):
            raise ValueError('invalid_review_span')
        item = record(selection['id'], source_ref(selection['path'], lines, start, end, digest),
            selection['context'], line['text'].rstrip('*'), selection['logic'],
            selection['preferred'], selection['avoid'], selection['domain'], 'approved', selection['stage'])
        item['evidence_quote'] = line['raw']
        item['evidence_line'] = line['line']
        item['tags'] = selection['tags']
        if 'behavior' in selection:
            behavior = dict(selection['behavior'])
            required = {'trigger', 'observed_actions', 'inferred_motive', 'response_options', 'stop_conditions', 'capability_boundary'}
            if set(behavior) != required or not behavior['observed_actions']:
                raise ValueError('invalid_behavior_fields:' + selection['id'])
            for field in ('response_options', 'stop_conditions', 'capability_boundary'):
                if not isinstance(behavior[field], list) or not all(isinstance(s, str) and s for s in behavior[field]):
                    raise ValueError('invalid_behavior_list')
            evidence = []
            for action in behavior['observed_actions']:
                a, b = action['span']
                if not start <= a <= b <= end:
                    raise ValueError('action_evidence_outside_review:' + selection['id'])
                evidence.append(dict(action=action['action'], line_start=a, line_end=b,
                    quote='\n'.join(l['raw'] for l in lines[a - 1:b])))
            behavior['observed_actions'] = evidence
            behavior['inference_is_fact'] = False
            item['behavior'] = behavior
        approved.append(item)
    if len({s['id'] for s in approved + drafts}) != len(approved + drafts):
        raise ValueError('duplicate_id')
    write_jsonl(output / 'drafts' / 'story_windows.jsonl', drafts)
    write_jsonl(output / 'reviewed' / 'story_evidence.jsonl', approved)
    catalog = ['# 左然的情境化行为证据', '', '观察到的行为有逐行出处；人物动机为整理推断，不是必然规则或自动执行授权。', '']
    for item in approved:
        behavior = item.get('behavior')
        if not behavior:
            continue
        catalog.extend(['## ' + item['id'], '', '**情境：** ' + behavior['trigger'], '',
            '**剧情中的行为：** ' + '；'.join(a['action'] for a in behavior['observed_actions']), '',
            '**可参考的方向：** ' + '；'.join(behavior['response_options']), '',
            '**停止或不适用：** ' + '；'.join(behavior['stop_conditions']), '',
            '**出处：** [' + item['source_ref']['location'] + '](../../' + item['source_ref']['path'] + ')', ''])
    (output / 'behavior_catalog.md').write_text('\n'.join(catalog), encoding='utf-8')
    report = dict(files=manifest, approved=len(approved),
        draft=sum(d['review_status'] == 'draft' for d in drafts),
        reviewed_source_windows=sum(d['review_status'] == 'reviewed' for d in drafts),
        extracted_windows=len(drafts), behavior_records=sum('behavior' in a for a in approved),
        speaker_mapping={'我': 'user (剧情中的用户角色，不是现实用户记忆)', '左然': 'libra',
                         '你及其他标签': 'other; 不自动纠正', '无标签': '仅已确认独白文件正文归左然，其余narration_or_unattributed'},
        scope='Full-text review tracked per file; only approved scene evidence is retrievable.')
    (output / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--selections', type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.repo, args.output, load_selections(args.selections))
    print(json.dumps(report, ensure_ascii=False, indent=2))
