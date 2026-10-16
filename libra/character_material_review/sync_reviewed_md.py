"""Sync user-reviewed Markdown without importing material into the live store."""
from collections import Counter
from datetime import datetime
import copy
import csv
import hashlib
import json
from pathlib import Path
import re

from build_materials import HERE, ROOT, live_counts


def main():
    md_path = HERE / '左然语料待筛选.md'
    json_path = HERE / '左然语料候选.json'
    raw = md_path.read_bytes()
    md = raw.decode('utf-8').replace('\r\n', '\n')
    document = json.loads(json_path.read_text(encoding='utf-8'))
    old = {e['id']: e for e in document['entries']}
    before = live_counts()
    matches = list(re.finditer(r'^### (ZR-[\d-]+) · (.*)$', md, re.M))
    assert matches and len(matches) == len({m[1] for m in matches})
    entries = []
    for i, match in enumerate(matches):
        identity, title = match.groups()
        assert identity in old, ('Unknown ID', identity)
        if '删除' in title:
            continue
        body = md[match.end():matches[i+1].start() if i+1<len(matches) else len(md)]
        front = body.split('<details>')[0]
        fields = dict(re.findall(r'^\*\*([^\n]+?)：\*\* (.*)$', front, re.M))
        required = ['适用情境', '左然的反应特点（整理推断）', '剧情实例·背景', '剧情实例·反应']
        assert all(fields.get(k) for k in required), identity
        e = copy.deepcopy(old[identity])
        classification = re.search(r'^分类：(.*?)｜主题：(.*?)｜来源：(.*?) · (.*?)｜(.*?)$', front, re.M)
        assert classification, identity
        label, topic, source_title, stage, kind = classification.groups()
        assert label in ['涉及用户', '左然自身']
        assert stage == e['source_stage'] and source_title == e['source_ref']['title']
        e.update(title=title, subject_label=label, subject_scope='user_related' if label=='涉及用户' else 'zuoran_self',
                 topic=topic, relationship_related=kind=='感情参考',
                 situation=fields['适用情境'], applicable_situation=fields['适用情境'],
                 response_pattern=fields['左然的反应特点（整理推断）'],
                 interpretation=fields['左然的反应特点（整理推断）'],
                 interpretation_status='用户已复核的整理推断；不是人物必然规律',
                 story_context=fields['剧情实例·背景'], observed_response=fields['剧情实例·反应'],
                 review_status='reviewed', review_method='user_edited_markdown', database_imported=False)
        assert not e['relationship_related'] or e['source_group'] in ['挚爱篇', '相守篇']
        e['retrieval_summary'] = e['situation'] + ' ' + e['response_pattern']
        e['retrieval'].update(query_document=' '.join([e['situation'],e['response_pattern'],e['topic']]),
            supporting_query_document=e['story_context']+' '+e['observed_response'],
            primary_fields=['applicable_situation','response_pattern','topic'],
            secondary_fields=['story_context','observed_response'],
            retrieval_subject=e['subject_scope'], runtime_enabled=False)
        # Read the current excerpts, never restore text removed by the user.
        excerpts = re.findall(r'<summary>对应原文 · (.*?) · L(\d+)–L(\d+)</summary>\s*````text\n(.*?)\n````', body, re.S)
        assert excerpts, identity
        e['excerpts'] = []
        for j,(path,a,b,text) in enumerate(excerpts,1):
            assert path == e['source_ref']['path']
            source = (ROOT/path).resolve()
            assert source.is_relative_to(ROOT/'libra')
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            assert source_hash == e['source_ref']['sha256']
            lines = source.read_text(encoding='utf-8-sig').splitlines()
            a,b=int(a),int(b)
            assert 1<=a<=b<=len(lines) and text=='\n'.join(lines[a-1:b]), identity
            e['excerpts'].append(dict(excerpt_id=f'{identity}-P{j:02d}',material_id=identity,
                source_path=path,line_start=a,line_end=b,source_sha256=source_hash,text=text))
        quote = re.search(r'^> (.*)$',front,re.M)
        attribution = re.search(r'^原话归属：(.*?)（L(\d+)）。',front,re.M)
        assert quote and attribution, identity
        number=int(attribution[2])
        assert any(x['line_start']<=number<=x['line_end'] for x in e['excerpts'])
        assert lines[number-1]==quote[1], identity
        e['direct_quote'].update(line=number,text=quote[1],attribution=attribution[1])
        entries.append(e)
    ids={e['id'] for e in entries}
    for e in entries:
        assert all(x in ids for x in e.get('read_together',[])), ('Missing linked material',e['id'])
    removed=sorted(set(document.get('removed_ids',[])) | (set(old)-ids))
    counts=dict(Counter(e['subject_label'] for e in entries))
    document.update(schema_version=2,review_complete=True,review_authority=md_path.name,
        database_imported=False,removed_ids=removed,counts=counts,entries=entries)
    document['rules']['retrieval']='重点检索适用情境与反应特点；具体剧情实例辅助判断，原文按物料编号读取。'
    document['rules']['pronouns']='叙述中的我为当前用户，左然为角色；引文中的人称由说话人确定。'
    document['rules']['married_reference']='同居后和结婚后的感情互动均可作为当前婚后参考；个人线仅保留非恋爱参考。'
    for source in document['sources']:
        source['candidate_count']=sum(e['source_ref']['path']==source['path'] for e in entries)
    archive=HERE/'用户复核存档'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    archive.mkdir(parents=True)
    for name in [md_path.name,json_path.name,'左然语料筛选表.csv','构建校验.json']:
        (archive/name).write_bytes((HERE/name).read_bytes())
    assert md_path.read_bytes()==raw, 'MD changed while syncing'
    json_path.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (HERE/'左然语料筛选表.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f)
        w.writerow(['编号','筛选决定','修改意见','分类','主题','来源阶段','是否感情参考','适用情境','左然的反应特点','剧情实例·背景','剧情实例·反应','对应原话','原文出处'])
        for e in entries:
            w.writerow([e['id'],'保留','已按用户完成的 MD 复核同步',e['subject_label'],e['topic'],e['source_stage'],
                '是' if e['relationship_related'] else '否',e['situation'],e['response_pattern'],e['story_context'],
                e['observed_response'],e['direct_quote']['text'],'; '.join(f"{x['source_path']}:L{x['line_start']}-L{x['line_end']}" for x in e['excerpts'])])
    updated=re.sub(r'^本轮从 .*?条。$',f'本轮已按你完成的 MD 复核同步：保留 {len(entries)} 条，涉及用户 {counts["涉及用户"]} 条，左然自身 {counts["左然自身"]} 条；相对最初候选移除 {len(removed)} 条。',md,count=1,flags=re.M)
    updated=updated.replace('未标记的是否通过，以本轮复核完成时你的说明为准。','本轮以你完成的 MD 为准，保留的条目已同步至 JSON 和 CSV。')
    updated=updated.replace('这批是新建的筛选稿，尚未入库。','这批已完成本轮用户复核，尚未入库。')
    # All user-edited event blocks remain byte-for-byte equivalent as text.
    assert updated[updated.index('### ZR-'):]==md[md.index('### ZR-'):]
    md_path.write_bytes((updated.replace('\n', '\r\n') if b'\r\n' in raw else updated).encode('utf-8'))
    assert live_counts()==before
    report=dict(retained_count=len(entries),removed_count=len(removed),removed_ids=removed,
        classification_counts=counts,stage_counts=dict(Counter(e['source_stage'] for e in entries)),
        all_excerpts_exact=True,all_direct_quotes_exact=True,user_event_blocks_preserved=True,
        review_complete=True,database_imported=False,live_database_counts_unchanged=True,
        database_counts=before,archive=str(archive.relative_to(ROOT)))
    (HERE/'复核同步校验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
