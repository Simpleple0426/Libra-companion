"""Build offline review artifacts. Does not import application code or write databases."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def database_counts():
    results = {}
    for path in sorted((ROOT / 'backend').glob('*.db')):
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            names = [name for name in tables if name in {
                'character_corpus_v2', 'character_corpus_v2_fts',
                'character_corpus_v2_embeddings', 'canonical_shared_history',
                'canonical_shared_history_fts', 'canonical_shared_history_chunks',
                'canonical_shared_history_chunks_fts', 'canonical_shared_history_embeddings',
                'canonical_shared_history_chunk_embeddings',
            }]
            results[path.name] = {
                name: connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                for name in sorted(names)
            }
        finally:
            connection.close()
    return results


def main():
    review_csv = HERE / '共同经历筛选表.csv'
    if (HERE / '细化校验.json').exists():
        raise RuntimeError('已有细化稿，请使用 refine_review.py，不能覆盖用户筛选结果。')
    if review_csv.exists():
        reviewed = list(csv.DictReader(review_csv.open(encoding='utf-8-sig', newline='')))
        if any(r.get('筛选决定（保留/删除/修改）', '').strip() or r.get('修改意见或替换摘要', '').strip() for r in reviewed):
            raise RuntimeError('CSV 已有用户筛选意见，拒绝重建覆盖。')
    notes = {}
    for file in sorted(HERE.glob('draft_notes*.json')):
        batch = json.loads(file.read_text(encoding='utf-8'))
        assert not notes.keys() & batch.keys(), 'Duplicate source'
        notes.update(batch)
    sources = [ROOT / 'libra' / '个人线' / f'第{n}章.md' for n in '一二三四']
    sources += sorted((ROOT / 'libra' / '卡面').rglob('*.md'))
    assert len(sources) == 26
    assert {p.stem for p in sources} == set(notes), 'Missing or extra source'
    before_hashes = {p: digest(p) for p in sources}
    before_db = database_counts()
    records, manifest = [], []
    for source_number, path in enumerate(sources, 1):
        lines = path.read_text(encoding='utf-8-sig').splitlines()
        starts = [(i, re.sub(r'^#+\s*', '', line).strip())
                  for i, line in enumerate(lines)
                  if re.match(r'^#{2,3}\s+', line)]
        sections = {
            label: (start + 1, starts[j + 1][0] if j + 1 < len(starts) else len(lines))
            for j, (start, label) in enumerate(starts)
        }
        source_id = f'S{source_number:02d}'
        relative = path.relative_to(ROOT).as_posix()
        if '个人线' in path.parts:
            stage = '搭档／关系发展期'
        elif '相守篇' in path.parts:
            stage = '婚礼／婚后（依具体事件）'
        else:
            stage = '恋爱／共同生活（按来源分类，不作跨篇时间推断）'
        manifest.append({
            'source_id': source_id, 'path': relative,
            'sha256': before_hashes[path], 'line_count': len(lines),
            'byte_count': path.stat().st_size,
            'candidate_count': len(notes[path.stem]),
            'original_section_labels': list(sections),
            'processing_status': 'candidate_summaries_prepared',
            'line_by_line_exhaustive_review': False,
        })
        for number, row in enumerate(notes[path.stem], 1):
            section, title, summary, *kind = row
            assert section in sections, (relative, section)
            a, b = sections[section]
            assert 1 <= a <= b <= len(lines)
            assert title.strip() and summary.strip() and '\ufffd' not in summary
            records.append({
                'id': f'SH-{source_number:02d}-{number:02d}',
                'review_status': 'pending_user_review',
                'decision': '', 'review_note': '',
                'title': title, 'summary': summary,
                'event_type': kind[0] if kind else '剧情中发生的共同互动',
                'participants': ['左然', '剧情中的我'],
                'source_relationship_context': stage,
                'temporal_scope': '仅剧情相对时间；不映射现实日期',
                'source_ref': {
                    'source_id': source_id, 'path': relative, 'section': section,
                    'line_start': a, 'line_end': b, 'sha256': before_hashes[path],
                    'range_precision': '原文完整章节范围；可能含本条以外的内容',
                },
            })
    assert len({record['id'] for record in records}) == len(records)
    assert all(record['review_status'] == 'pending_user_review' for record in records)
    artifact = {
        'schema_version': 1,
        'purpose': '仅供筛选的剧情共同经历候选；不是人物语料，不直接导入运行时',
        'user_review_complete': False, 'database_imported': False,
        'scope': {
            'source_files': 26, 'personal_route_files': 4, 'card_files': 22,
            'narrator_mapping': '我指原文女主；不自动视为现实用户已经经历的事实',
            'ordering': '按原始文件分类和篇内顺序；不同卡面未强行合成时间线',
            'coverage': '按剧情章节提炼候选并核对关键段落，未宣称逐句穷尽',
        },
        'sources': manifest, 'entries': records,
    }
    (HERE / '共同经历候选.json').write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    with (HERE / '共同经历筛选表.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['编号', '筛选决定（保留/删除/修改）', '修改意见或替换摘要',
                         '来源', '章节', '标题', '共同经历摘要', '经历类型',
                         '原文关系背景', '原文路径', '起始行', '结束行'])
        for record in records:
            ref = record['source_ref']
            writer.writerow([record['id'], '', '', Path(ref['path']).stem,
                             ref['section'], record['title'], record['summary'],
                             record['event_type'], record['source_relationship_context'],
                             ref['path'], ref['line_start'], ref['line_end']])
    md = [
        '# 左然剧情共同经历 · 待筛选稿', '',
        f'来源：4 个个人线 MD、22 个卡面 MD。共 {len(records)} 条候选，全部待你筛选，未写入数据库。', '',
        '“我”均指剧情中的女主。本文只整理双方参与的事件、相处和明确回忆；不提炼性格、行为规则或台词语料。', '',
        '可以在下方勾选希望保留的条目，也可以打开 [筛选表](共同经历筛选表.csv)，填写第二列“保留／删除／修改”，第三列填写意见或替换摘要。未勾选、未填写均表示尚未决定。', '',
        '每条附原文文件、章节和行号。行号覆盖原文完整章节，不表示该章节每句话都支持摘要；遇到拿不准的细节，应回原文核对。此稿按章节提炼并核对关键段落，不宣称逐句穷尽。', '',
        '按文件分类排列，不把不同卡面强行排成年月时间线。婚礼、婚后、回忆、梦境相关互动保留来源背景，供你决定是否纳入；不会自动成为现实用户的记忆。', '',
        '## 来源目录', '',
        '| 来源 | 候选数 | |', '| --- | ---: | --- |',
    ]
    for source in manifest:
        md.append(f"| {Path(source['path']).stem} | {source['candidate_count']} | [查看](#{source['source_id'].lower()}) |")
    for source in manifest:
        md.extend(['', f'<a id="{source["source_id"].lower()}"></a>', '',
                   f'## {Path(source["path"]).stem}', '',
                   f'原文：{source["path"]}；{source["candidate_count"]} 条候选。', ''])
        for record in records:
            ref = record['source_ref']
            if ref['source_id'] != source['source_id']:
                continue
            link = quote((ROOT / ref['path']).as_posix(), safe='/:')
            md.extend([
                f'- [ ] **{record["id"]} · {record["title"]}**', '',
                f'  {record["summary"]}', '',
                f'  类型：{record["event_type"]}。出处：[{Path(ref["path"]).name} · {ref["section"]} · L{ref["line_start"]}–L{ref["line_end"]}]({link}:{ref["line_start"]})。', '',
            ])
    md.extend([
        '## 暂不扩写的部分', '',
        '- 第三方单独发生的案件经过、父母和长辈的人生、电影内部故事：仅保留双方一起调查、倾听、观影和讨论的事件。',
        '- 纯独处心理、未经落实的旅行或礼物约定：不写成已完成事件。',
        '- 原文梦境、假设及节俗中的感应：不转成实际发生的事实；醒后交流可以作为相处事件。',
        '- 《mr梦迟》保留独白来源标记，仪式梦境不重复计作第二次婚礼。',
        '- 原文缺号章节（如《遐梦蹁跹》没有单列第 4 节、《抵晴》没有单列第 2 节）沿用原文件范围，不补造缺失内容。', '',
        '筛选后的修改应以你的意见为准。目前没有自动导入、自动认定通过或恢复旧语料的步骤。', '',
    ])
    (HERE / '共同经历待筛选.md').write_text('\n'.join(md), encoding='utf-8')
    after_db = database_counts()
    assert before_db == after_db, 'Corpus database counts changed during build'
    assert all(digest(path) == value for path, value in before_hashes.items()), 'Source modified'
    assert len(list(csv.reader((HERE / '共同经历筛选表.csv').open(encoding='utf-8-sig')))) == len(records) + 1
    report = {
        'source_files': len(sources), 'entries': len(records),
        'all_pending_user_review': True, 'unique_ids': True,
        'all_source_ranges_valid': True, 'source_hashes_unchanged': True,
        'database_counts_unchanged': before_db == after_db,
        'database_counts': after_db,
        'event_types': dict(Counter(record['event_type'] for record in records)),
        'limitations': ['Source coverage is chapter-based, not a line-by-line exhaustive audit.',
                        'Counts establish logical emptiness, not secure erasure.'],
    }
    (HERE / 'verification.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
