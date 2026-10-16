"""Apply the user's CSV decisions and build event-bound, offline source excerpts."""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
from collections import Counter
from build_review import database_counts

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CSV = HERE / '共同经历筛选表.csv'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def prepare():
    archive = HERE / '第一轮存档'
    archive.mkdir(exist_ok=True)
    for name in ['共同经历筛选表.csv', '共同经历候选.json', '共同经历待筛选.md']:
        target = archive / name
        if not target.exists():
            target.write_bytes((HERE / name).read_bytes())
    baseline = json.loads((archive / '共同经历候选.json').read_text(encoding='utf-8'))
    return baseline

def main():
    if (HERE/'第二轮复核校验.json').exists():
        raise RuntimeError('第二轮已按用户修改的 MD 同步，拒绝用旧规格覆盖。')
    new_csv=HERE/'共同经历细化复核表.csv'
    if new_csv.exists():
        existing=list(csv.DictReader(new_csv.open(encoding='utf-8-sig',newline='')))
        assert not any(r.get('复核决定','').strip() or r.get('复核意见','').strip() for r in existing),'Refusing to overwrite user review'
    baseline = prepare()
    rows = list(csv.DictReader(CSV.open(encoding='utf-8-sig', newline='')))
    original = {r['id']: r for r in baseline['entries']}
    assert len(rows) == len(original) and {r['编号'] for r in rows} == set(original)
    specs = {}
    for spec_file in sorted(HERE.glob('refinement_specs*.json')):
        batch = json.loads(spec_file.read_text(encoding='utf-8'))
        assert not set(batch) & set(specs)
        specs.update(batch)
    selected = {r['编号']: r for r in rows if r['筛选决定（保留/删除/修改）'].strip() != '删除'}
    assert set(specs) == set(selected), (set(selected)-set(specs),set(specs)-set(selected))
    assert all(r['筛选决定（保留/删除/修改）'].strip() in {'','保留','修改','删除'} for r in rows)
    before_csv = sha(CSV)
    before_db = database_counts()
    source_hashes = {s['path']: sha(ROOT/s['path']) for s in baseline['sources']}
    assert all(source_hashes[s['path']] == s['sha256'] for s in baseline['sources']), 'Original MD changed; review ranges first'
    entries=[]
    for old_id,row in selected.items():
        old=original[old_id]
        path=ROOT/old['source_ref']['path']
        lines=path.read_text(encoding='utf-8-sig').splitlines()
        for i,spec in enumerate(specs[old_id],1):
            ranges,title,summary,details=spec
            new_id=old_id if len(specs[old_id])==1 else f'{old_id}-{i:02d}'
            excerpts=[]
            for j,(a,b) in enumerate(ranges,1):
                assert 1<=a<=b<=len(lines),(new_id,a,b)
                excerpts.append({'excerpt_id':f'{new_id}-P{j:02d}', 'event_id':new_id,
                    'source_path':old['source_ref']['path'], 'line_start':a,'line_end':b,
                    'source_sha256':source_hashes[old['source_ref']['path']],
                    'text':'\n'.join(lines[a-1:b]),
                    'role':'source_evidence_with_context_not_independent_shared_facts'})
            assert summary and len(details)>=2 and all(details)
            entries.append({'id':new_id,'parent_id':old_id,'source_title':row['来源'],
                'title':title,'retrieval_summary':summary,'detailed_event':details,
                'selection_status':'retained_by_user',
                'detail_review_status':'refined_pending_user_review',
                'decision_basis':row['筛选决定（保留/删除/修改）'].strip() or '未标记即保留（用户确认）',
                'user_instruction':row['修改意见或替换摘要'],
                'event_type':old['event_type'],
                'source_relationship_context':old['source_relationship_context'],
                'participants':old['participants'],
                'source_ref':{'path':old['source_ref']['path'],'section':old['source_ref']['section'],
                              'sha256':source_hashes[old['source_ref']['path']]},
                'excerpts':excerpts,
                'retrieval_policy':{'retrieve_as_event':True,'fetch_excerpts_by_event_id':True,
                    'independent_excerpt_retrieval':False},
                'database_imported':False})
    ids=[e['id'] for e in entries]
    assert len(ids)==len(set(ids))
    restricted={'SH-16-06':(683,687),'SH-22-02':(231,254),'SH-24-04':(747,758),'SH-25-02':(182,238)}
    for e in entries:
        assert e['parent_id'] in selected
        if e['parent_id'] in restricted:
            a,b=restricted[e['parent_id']]
            assert all(a<=x['line_start']<=x['line_end']<=b for x in e['excerpts'])
    for e in entries:
        for x in e['excerpts']:
            source_lines=(ROOT/x['source_path']).read_text(encoding='utf-8-sig').splitlines()
            assert x['text']=='\n'.join(source_lines[x['line_start']-1:x['line_end']])
    sources=[]
    for source in baseline['sources']:
        source=dict(source)
        source['first_round_candidate_count']=source['candidate_count']
        source['candidate_count']=sum(e['source_ref']['path']==source['path'] for e in entries)
        source['processing_status']='user_selection_applied_details_pending_review'
        sources.append(source)
    result={'schema_version':2,'source_selection_complete':True,'detail_review_complete':False,
      'database_imported':False,'scope':'仅剧情共同经历；摘要与原文按事件绑定。新拆分和细化内容待复核。',
      'selection_counts':dict(Counter(r['筛选决定（保留/删除/修改）'].strip() or '未标记即保留' for r in rows)),
      'deleted_parent_ids':[r['编号'] for r in rows if r['筛选决定（保留/删除/修改）'].strip()=='删除'],
      'sources':sources,'entries':entries}
    (HERE/'共同经历候选.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    output=['# 左然剧情共同经历 · 细化复核稿','',
      f'已落实你的第一轮选择：115 条未标记视为保留，4 条按意见修改，45 条删除。119 条原条目整理为 {len(entries)} 个事件。','',
      '第一轮范围已经确认；下面只需复核拆分是否合适、经过是否准确、原文范围是否恰当。原 CSV 原样保留，旧稿在“第一轮存档”。','',
      '每个事件包含检索摘要、详细经过和可展开的原文。原文按事件编号绑定，不作为独立的、绕过筛选的检索库。尚未写入数据库或修改运行时。','',
      '原文可能含角色转述、回忆或电影对白，它们只是场景上下文；共同经历以本事件详细经过为界，不把第三方经历、梦境或愿望认定为双方实际经历。','',
      '[细化复核表](共同经历细化复核表.csv)中可填写“确认／修改／删除”及意见；无需重做第一轮筛选。','']
    previous=None
    for e in entries:
        if e['source_title']!=previous:
            previous=e['source_title'];output+=['',f'## {previous}','']
        output += [f'### {e["id"]} · {e["title"]}','',f'原编号：{e["parent_id"]}；类型：{e["event_type"]}。','',
                   f'**检索摘要：** {e["retrieval_summary"]}','','**详细经过：**','']
        output += [f'{i}. {d}' for i,d in enumerate(e['detailed_event'],1)]
        if e['user_instruction']:output+=['',f'已落实你的意见：{e["user_instruction"].strip()}']
        for x in e['excerpts']:
            output+=['', '<details>',f'<summary>原文 · {x["source_path"]} · L{x["line_start"]}–L{x["line_end"]}</summary>', '',
              '````text',x['text'],'````','','</details>','']
    (HERE/'共同经历待筛选.md').write_text('\n'.join(output)+'\n',encoding='utf-8')
    new_csv=HERE/'共同经历细化复核表.csv'
    if new_csv.exists():
        existing=list(csv.DictReader(new_csv.open(encoding='utf-8-sig',newline='')))
        assert not any(r.get('复核决定','').strip() or r.get('复核意见','').strip() for r in existing),'Refusing to overwrite user review'
    with new_csv.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['事件编号','原编号','复核决定','复核意见','来源','标题','检索摘要','详细经过','原文范围'])
        for e in entries:w.writerow([e['id'],e['parent_id'],'','',e['source_title'],e['title'],e['retrieval_summary'],
            '\n'.join(f'{i}. {s}' for i,s in enumerate(e['detailed_event'],1)),
            '; '.join(f'{x["source_path"]}:L{x["line_start"]}-L{x["line_end"]}' for x in e['excerpts'])])
    assert sha(CSV)==before_csv
    assert all(sha(ROOT/p)==h for p,h in source_hashes.items())
    after_db=database_counts();assert before_db==after_db
    report={'selected_parent_count':len(selected),'event_count':len(entries),
      'split_parent_count':sum(len(s)>1 for s in specs.values()),'deleted_count':len(result['deleted_parent_ids']),
      'original_csv_unchanged':True,'source_markdown_unchanged':True,'all_excerpts_exact':True,
      'no_deleted_parent_in_output':True,'database_counts_unchanged':True,'database_counts':after_db}
    report['four_partial_edits_have_restricted_excerpts']=True
    report['source_file_count']=len(source_hashes)
    (HERE/'细化校验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__': main()
