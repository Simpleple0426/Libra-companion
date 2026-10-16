"""Validated conversion of reviewed situations into the character retrieval store."""
import hashlib
import json
from pathlib import Path

from domains.memory.store import tokens
from domains.persona.corpus_pronouns import normalize_excerpt

PROJECT = Path(__file__).resolve().parents[3]
SOURCE = PROJECT / 'libra/character_material_review/左然语料候选.json'


def import_material(store, source=SOURCE):
    from domains.persona.character_corpus import validate_sample
    document = json.loads(Path(source).read_text(encoding='utf-8-sig'))
    if not document.get('review_complete') or document.get('schema_version') != 2:
        raise ValueError('Material review is incomplete')
    samples=[]
    for entry in document['entries']:
        if entry['review_status'] != 'reviewed':
            raise ValueError('Unreviewed material')
        ref=entry['source_ref']
        path=(PROJECT/ref['path']).resolve()
        if not path.is_relative_to(PROJECT/'libra'):
            raise ValueError('Invalid material source')
        content=path.read_bytes()
        digest=hashlib.sha256(content).hexdigest()
        lines=content.decode('utf-8-sig').splitlines()
        group=next((s for s in ['个人线','挚爱篇','相守篇'] if s in path.parts),None)
        if group != entry['source_group'] or digest != ref['sha256']:
            raise ValueError('Source changed')
        if entry['relationship_related'] and group not in ['挚爱篇','相守篇']:
            raise ValueError('Pre-confession romance cannot be imported')
        if not entry['excerpts']:
            raise ValueError('Missing excerpts')
        for x in entry['excerpts']:
            a,b=x['line_start'],x['line_end']
            if (x['material_id']!=entry['id'] or x['source_path']!=ref['path']
                or x['source_sha256']!=digest or not 1<=a<=b<=len(lines)
                or normalize_excerpt(x['text'])!=normalize_excerpt('\n'.join(lines[a-1:b]))):
                raise ValueError('Invalid bound excerpt')
        q=entry['direct_quote']
        if not 1<=q['line']<=len(lines) or q['text']!=lines[q['line']-1]:
            raise ValueError('Invalid quote')
        sample=dict(id=entry['id'],domain='relationship' if entry['relationship_related'] else 'behavior',
            type='reviewed_situational_material',source_level='explicit_canon',review_status='approved',version=2,
            confidence=1.0,source_ref={**ref,'work':ref['title'],'location':'; '.join(
                f"L{x['line_start']}-L{x['line_end']}" for x in entry['excerpts'])},
            context=entry['applicable_situation'],character_logic=entry['response_pattern'],
            preferred_direction=[entry['response_pattern']],avoid_direction=[],tags=[entry['topic']],
            subject_scope=entry['subject_scope'],source_stage=entry['source_stage'],
            applicability={'relationship_stage':'established_partner_in_story' if group!='个人线' else 'colleagues_in_story',
                'romance_reference_allowed':group!='个人线','stage_is_source_background':True},
            story_context=entry['story_context'],observed_response=entry['observed_response'],
            interpretation_status=entry['interpretation_status'],evidence_kind=entry['evidence_kind'],
            evidence_quote=q['text'],evidence_line=q['line'],quote_attribution=q['attribution'],
            bound_excerpts=entry['excerpts'],read_together=entry.get('read_together',[]))
        samples.append(validate_sample(sample))
    ids={s['id'] for s in samples}
    if not samples or len(ids)!=len(samples) or ids.intersection(document.get('removed_ids',[])):
        raise ValueError('Empty, duplicate or removed material')
    store.initialize()
    with store.connect() as c:
        c.execute('DELETE FROM character_corpus_v2')
        c.execute('DELETE FROM character_corpus_v2_fts')
        c.execute('DELETE FROM character_corpus_v2_embeddings')
        for sample in samples:
            c.execute('INSERT INTO character_corpus_v2 VALUES (?,?,?,?,?)',
                (sample['id'],sample['domain'],sample['source_level'],'approved',json.dumps(sample,ensure_ascii=False)))
            text=store._embedding_text(sample)+' '+sample['story_context']+' '+sample['observed_response']
            c.execute('INSERT INTO character_corpus_v2_fts VALUES (?,?)',(sample['id'],' '.join(sorted(tokens(text)))))
    return {'records':len(samples),'excerpts':sum(len(s['bound_excerpts']) for s in samples)}


def compact_material(sample, *, include_source=False):
    item={k:sample[k] for k in ['id','context','character_logic','subject_scope','source_stage',
        'story_context','observed_response','evidence_kind','interpretation_status','quote_attribution','evidence_quote']}
    item['source_excerpts']=[]
    item['source_refs'] = [dict(source_path=x['source_path'], line_start=x['line_start'],
                                line_end=x['line_end']) for x in sample['bound_excerpts']]
    if not include_source:
        item.pop('evidence_quote', None)
        return item
    remaining=1800
    for x in sample['bound_excerpts']:
        if remaining<=0:break
        # Show complete lines only, with accurate provenance for the shown span.
        shown=[]
        for line in x['text'].splitlines():
            if len('\n'.join(shown+[line]))>remaining:break
            shown.append(line)
        if not shown:continue
        text='\n'.join(shown)
        item['source_excerpts'].append(dict(material_id=sample['id'],source_path=x['source_path'],
            line_start=x['line_start'],line_end=x['line_start']+len(shown)-1,text=text,
            truncated=len(shown)<len(x['text'].splitlines())))
        remaining-=len(text)
    return item
