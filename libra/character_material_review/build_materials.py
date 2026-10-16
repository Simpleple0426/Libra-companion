"""Build offline situational material from original MD; never import to live memory."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from selections import ROWS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE_NAMES = [
    '第一章.md', '第二章.md', '第三章.md', '第四章.md', 'ssr与浪晴舞.md',
    'ssr共弦.md', 'ssr好雨知年.md', 'ssr如我自观.md', 'ssr如涉千山.md',
    'ssr影遇流年.md', 'ssr恋影流金.md', 'ssr恰是好时节.md', 'ssr旧年与沐.md',
    'ssr暮雪交辉.md', 'ssr柑饴.md', 'ssr理想几何.md', 'ssr遐梦蹁跹.md',
    'ssr霞花暮语.md', 'ssr风烛引归.md', 'sss同我仰春.md', 'sss溯影同生.md',
    'sss锦书枫回.md', 'mr梦迟.md', 'ssr抵晴.md', 'ssr然而佳期.md', 'ssr誓念天成.md',
]
PERSONAL_TOPICS = {'工作协作', '责任与选择', '职业判断', '工作支持', '公益工作', '理解他人', '调查应对'}
ROMANCE_TOPICS = {'感情支持', '感情表达', '共同决策', '日常心意', '亲密玩笑', '共同期待',
    '共同收藏', '回应心意', '礼物与心意', '共同生活', '亲密互动', '关系中的负担', '冲突修复',
    '异地心意', '婚后照顾', '婚后亲密', '婚后坦诚', '婚后支持', '婚后依恋', '公开支持',
    '婚后日常', '婚后纪念', '依恋表达', '关系修复', '婚姻观', '纪念与准备'}
# Explicitly distinguish remembered/quoted speech from dialogue spoken in the scene.
QUOTE_NOTES = {(6, 417): '用户回想左然在练习时的原话，不是演出当场说话',
               (7, 595): '左然引用用户以前说的话，体现他接受支持；不是他原创的格言',
               (13, 303): '回忆中左然对委托人的原话',
               (25, 369): '当前叙述回想早先尝培塔卷时左然的原话'}
SELF_HISTORY = {(1, 240), (5, 135), (6, 154), (8, 309), (13, 303),
                (15, 359), (15, 379), (16, 572), (16, 643), (24, 586)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def live_counts():
    result = {}
    for name in ['cognition.db', 'libra.db', 'content.db']:
        path = ROOT / 'backend' / name
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as con:
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            result[name] = {t: con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
                for t in ['character_corpus_v2', 'character_corpus_v2_fts', 'character_corpus_v2_embeddings',
                          'canonical_shared_history', 'canonical_shared_history_chunks',
                          'canonical_shared_history_embeddings'] if t in names}
    return result


def main():
    report_file = HERE / '构建校验.json'
    if report_file.exists():
        previous = json.loads(report_file.read_text(encoding='utf-8'))
        for name, value in previous['output_hashes'].items():
            if not (HERE / name).exists() or digest(HERE / name) != value:
                raise ValueError(f'用户可能已修改 {name}，拒绝覆盖；应先同步复核内容')
    elif any((HERE / n).exists() for n in ['左然语料待筛选.md', '左然语料候选.json', '左然语料筛选表.csv']):
        raise ValueError('Existing review files without build report; refusing to overwrite')
    before = live_counts()
    history_hashes = {p: digest(p) for p in (ROOT / 'libra/shared_history_review').glob('*') if p.is_file()}
    paths = [*sorted((ROOT/'libra/个人线').rglob('*.md')), *sorted((ROOT/'libra/卡面').rglob('*.md'))]
    assert len(paths) == 26 and len({p.name for p in paths}) == 26
    by_name = {p.name: p for p in paths}
    assert set(SOURCE_NAMES) == set(by_name)
    manifest, sources = [], {}
    for number, name in enumerate(SOURCE_NAMES, 1):
        p = by_name[name]
        path = p.relative_to(ROOT).as_posix()
        group = '个人线' if '个人线' in p.parts else '挚爱篇' if '挚爱篇' in p.parts else '相守篇'
        stage = {'个人线': '告白前', '挚爱篇': '同居后', '相守篇': '结婚后'}[group]
        lines = p.read_text(encoding='utf-8-sig').splitlines()
        source = dict(source_id=f'S{number:02d}', path=path, title=p.stem, group=group,
                      stage=stage, sha256=digest(p), line_count=len(lines))
        sources[number] = (source, lines)
        manifest.append(source)
    entries, counters = [], Counter()
    for n, a, b, q, subject, topic, situation, observation, interpretation in ROWS:
        source, lines = sources[n]
        assert 1 <= a <= q <= b <= len(lines)
        quote = lines[q-1]
        assert n == 23 or re.match(r'^(?:\*\*)?左然[：:]', quote), (n, q, quote)
        if n <= 4:
            assert topic in PERSONAL_TOPICS
            # This guard supplements the manual content review, not a classifier.
            assert not re.search('亲吻|告白|恋爱|婚后|撒娇|追求你', situation + observation + interpretation)
        romantic = topic in ROMANCE_TOPICS
        assert not romantic or source['group'] != '个人线'
        counters[n] += 1
        identity = f'ZR-{n:02d}-{counters[n]:02d}'
        subject_code = 'user_related' if subject == '用户' else 'zuoran_self'
        summary = situation + '时，' + observation
        excerpt = dict(excerpt_id=identity+'-P01', material_id=identity, source_path=source['path'],
                       line_start=a, line_end=b, source_sha256=source['sha256'], text='\n'.join(lines[a-1:b]))
        entry = dict(id=identity, review_status='draft', title=situation, subject_scope=subject_code,
            subject_label='涉及用户' if subject=='用户' else '左然自身', topic=topic,
            relationship_related=romantic, source_stage=source['stage'], source_group=source['group'],
            situation=situation, retrieval_summary=summary,
            observed_response=observation, interpretation=interpretation,
            interpretation_status='整理推断，待用户复核；不是人物必然规律',
            evidence_kind='past_self_report' if (n,q) in SELF_HISTORY else 'situational_source_evidence',
            source_ref={k:source[k] for k in ['source_id','path','title','sha256']},
            direct_quote={'speaker':'左然', 'line':q, 'text':quote,
                          'attribution':QUOTE_NOTES.get((n,q), '用户已确认全文独白归左然' if n==23 else '原文明示左然发言')},
            excerpts=[excerpt],
            applicability={'current_married_relationship_reference': n>4,
                'personal_route_usage': '仅工作与非恋爱处事参考' if n<=4 else None,
                'source_stage_is_not_current_stage':True},
            retrieval={'query_document':' '.join([situation, observation, interpretation, topic]),
                'retrieval_subject':subject_code, 'fetch_excerpts_by_material_id':True,
                'standalone_raw_excerpt_retrieval':False, 'runtime_enabled':False,
                'write_as_user_memory':False, 'write_as_shared_history':False},
            database_imported=False)
        if identity == 'ZR-22-02':
            entry['read_together']=['ZR-22-03', 'ZR-22-04']
        entries.append(entry)
    assert len(entries) == len({e['id'] for e in entries})
    assert len(counters)==26
    for source in manifest:
        source['candidate_count']=sum(e['source_ref']['path']==source['path'] for e in entries)
        source['coverage']='已选片段整理，非逐句穷尽'
    counts=dict(Counter(e['subject_label'] for e in entries))
    document={'schema_version':1,'kind':'situational_character_material','review_complete':False,
        'database_imported':False,'rules':{
            'classification':'依据情境关注谁，不是依据左然在跟谁说话；向用户倾诉自己的工作也可属于左然自身。',
            'romance_sources':['挚爱篇','相守篇'],
            'personal_route':'仅工作、职业判断、责任等非恋爱参考，不收录追求、暧昧、告白方式。',
            'memory_use':'未来可在同一召回入口检索自身经历和情境反应，但保留角色物料身份；不自动写成用户或双方共同经历。',
            'facts_and_inference':'原文和观察分别保存；可参考方向属于整理推断，不把一次行为提升成永远如此。'},
        'source_count':len(manifest),'counts':counts,'sources':manifest,'entries':entries}
    json_file=HERE/'左然语料候选.json'
    json_file.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    output=['# 左然情境语料 · 待筛选','',
        f'本轮从 4 个个人线 MD 与 22 个卡面 MD 整理 {len(entries)} 条候选：涉及用户 {counts["涉及用户"]} 条，左然自身 {counts["左然自身"]} 条。','',
        '直接在本文件改梗概、可参考方向即可；不想要的在标题旁标“删除”，请保留编号。也可用“左然语料筛选表.csv”，两处选一种修改即可。未标记的是否通过，以本轮复核完成时你的说明为准。','',
        '“左然自身”指关注他的状态、习惯、判断和选择，即使这段是他向用户倾诉，也归这里。涉及亲密关系的自身反应仍标“感情参考”。','',
        '**来源规则：个人线只作工作与非恋爱处事参考；感情相关仅使用挚爱篇、相守篇。** 来源阶段不是当前阶段；篇内过去的回忆仍是过去。','',
        '每条按“情境 → 梗概（原文中的反应）→ 原话 → 可参考方向 → 展开原文”排列。可参考方向是整理推断，原话保留原 MD 的文字及转录错字。','',
        '这批是新建的筛选稿，尚未入库。共同经历库及其 119 条事件保持不变。已覆盖全部 26 个来源，但没有宣称逐句提取了全部可用行为。','',
        '后续召回：先检索情境与梗概，再按本条编号取原文；“涉及用户”“左然自身”都可参与检索。自身反应可帮助理解“我在这种时候通常如何应对”，明确的自身往事可供谈及过去；两者都不自动变成与用户共同发生过的事。','']
    for label in ['涉及用户','左然自身']:
        output += [f'## {label}','']
        for e in [e for e in entries if e['subject_label']==label]:
            source=e['source_ref'];x=e['excerpts'][0];quote=e['direct_quote']
            output += [f'### {e["id"]} · {e["title"]}','',
                f'分类：{e["subject_label"]}｜主题：{e["topic"]}｜来源：{source["title"]} · {e["source_stage"]}｜'+('感情参考' if e['relationship_related'] else '非恋爱主题'),' ',
                '**情境：** '+e['situation'],'','**梗概：** '+e['observed_response'],'',
                '**对应原话：**','', '> '+quote['text'],'',
                f'原话归属：{quote["attribution"]}（L{quote["line"]}）。','',
                '**可参考方向（整理推断）：** '+e['interpretation'],'']
            if e.get('read_together'):
                output += ['需连同后续谈开一起理解：'+ '、'.join(e['read_together'])+'。','']
            output += ['<details>',f'<summary>对应原文 · {source["path"]} · L{x["line_start"]}–L{x["line_end"]}</summary>',
                       '', '````text',x['text'],'````','','</details>','']
    md_file=HERE/'左然语料待筛选.md'
    md_file.write_text('\n'.join(output)+'\n',encoding='utf-8')
    csv_file=HERE/'左然语料筛选表.csv'
    with csv_file.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['编号','筛选决定','修改意见','分类','主题','来源阶段','是否感情参考','情境','梗概','可参考方向','对应原话','原文出处'])
        for e in entries:
            x=e['excerpts'][0]
            writer.writerow([e['id'],'','',e['subject_label'],e['topic'],e['source_stage'],
                '是' if e['relationship_related'] else '否',e['situation'],e['observed_response'],e['interpretation'],
                e['direct_quote']['text'],f"{x['source_path']}:L{x['line_start']}-L{x['line_end']}"])
    after=live_counts()
    assert before==after
    assert all(digest(ROOT/s['path'])==s['sha256'] for s in manifest)
    assert all(digest(path)==value for path,value in history_hashes.items())
    for e in entries:
        x=e['excerpts'][0]
        lines=(ROOT/x['source_path']).read_text(encoding='utf-8-sig').splitlines()
        assert '\n'.join(lines[x['line_start']-1:x['line_end']])==x['text']
        assert lines[e['direct_quote']['line']-1]==e['direct_quote']['text']
    report={'candidate_count':len(entries),'classification_counts':counts,
        'source_count':len(manifest),'personal_route_nonromantic_count':sum(e['source_group']=='个人线' for e in entries),
        'personal_route_romantic_count':sum(e['source_group']=='个人线' and e['relationship_related'] for e in entries),
        'all_excerpts_exact':True,'all_quotes_exact':True,'original_markdown_unchanged':True,
        'shared_history_files_unchanged':True,'live_database_counts_unchanged':True,'database_counts':after,
        'all_candidates_pending_user_review':True,'old_corpus_or_backup_reused':False,
        'coverage_limitation':'人工选取的情境片段；并非全文逐句穷尽抽取。',
        'output_hashes':{f.name:digest(f) for f in [json_file,md_file,csv_file]}}
    report_file.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='output_hashes'},ensure_ascii=False))


if __name__=='__main__':
    main()
