"""Reviewed character evidence, isolated from user memories and legacy corpus."""
import json
import math
import re
import sqlite3
import hashlib
from contextlib import contextmanager
from pathlib import Path
from domains.memory.store import tokens
from infrastructure.embeddings.local import normalized

ROOT=Path(__file__).resolve().parents[3]/'libra'/'character_material_review'
LEVELS={'explicit_canon','canon_inference','approved_extension','runtime_generated'}
DOMAINS={'dialogue','cognition','behavior','emotion','relationship','initiative','daily_life','desire','anti_patterns'}


def validate_sample(data):
    required={'id','domain','type','source_level','source_ref','context','character_logic','preferred_direction','avoid_direction','confidence','review_status','version'}
    if not isinstance(data,dict) or required-set(data):raise ValueError('missing_corpus_fields')
    if data['domain'] not in DOMAINS or data['source_level'] not in LEVELS:raise ValueError('invalid_corpus_category')
    if data['review_status'] not in {'draft','reviewed','approved','rejected'}:raise ValueError('invalid_review_status')
    if type(data['confidence']) not in (int,float) or not math.isfinite(data['confidence']) or not 0<=data['confidence']<=1:raise ValueError('invalid_confidence')
    if type(data['version']) is not int or data['version']<1:raise ValueError('invalid_corpus_version')
    if not isinstance(data['source_ref'],dict):raise ValueError('invalid_source_ref')
    for field in ('id','type','context','character_logic'):
        if not isinstance(data[field],str) or not data[field].strip():raise ValueError('invalid_corpus_text')
    for field in ('preferred_direction','avoid_direction'):
        if not isinstance(data[field],list) or any(not isinstance(s,str) for s in data[field]):raise ValueError('invalid_corpus_directions')
    if data['review_status']=='approved':
        if data['source_level']=='runtime_generated':raise ValueError('runtime_cannot_be_canon')
        if not all(data['source_ref'].get(k) for k in ('work','location')):raise ValueError('approved_source_untraceable')
    return data


class CharacterCorpusStore:
    def __init__(self,path,embedding_adapter=None):
        self.path=path
        self.embedding_adapter=embedding_adapter

    @contextmanager
    def connect(self):
        from infrastructure.sqlite.connection import connect
        connection=connect(self.path)
        try:
            with connection:yield connection
        finally:connection.close()

    def initialize(self):
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS character_corpus_v2 (id TEXT PRIMARY KEY, domain TEXT NOT NULL, source_level TEXT NOT NULL, review_status TEXT NOT NULL, payload TEXT NOT NULL)')
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS character_corpus_v2_fts USING fts5(id UNINDEXED,search_text)")
            c.execute('''CREATE TABLE IF NOT EXISTS character_corpus_v2_embeddings (
                id TEXT PRIMARY KEY, model_id TEXT NOT NULL, dimensions INTEGER NOT NULL,
                content_hash TEXT NOT NULL, vector_json TEXT NOT NULL)''')

    @staticmethod
    def _embedding_text(sample):
        if sample.get('type') == 'reviewed_situational_material':
            return ' '.join([sample['context'],sample['character_logic'],*sample.get('tags',[])])
        behavior=sample.get('behavior') or {}
        return ' '.join([sample.get('context',''),sample.get('character_logic',''),
            *sample.get('preferred_direction',[]),*sample.get('tags',[]),
            behavior.get('trigger',''),*behavior.get('response_options',[])])

    def refresh_embeddings(self, batch_size=64):
        if self.embedding_adapter is None:return {'embedded':0,'enabled':False}
        model_id=str(self.embedding_adapter.model_id);dimensions=int(self.embedding_adapter.dimensions)
        with self.connect() as c:
            rows=c.execute('''SELECT id,payload FROM character_corpus_v2
                WHERE review_status='approved' AND source_level!='runtime_generated' ORDER BY id''').fetchall()
            existing={row[0]:row[1] for row in c.execute(
                'SELECT id,content_hash FROM character_corpus_v2_embeddings WHERE model_id=? AND dimensions=?',
                (model_id,dimensions))}
        pending=[]
        for record_id,payload in rows:
            sample=json.loads(payload);text=self._embedding_text(sample)
            digest=hashlib.sha256(text.encode('utf-8')).hexdigest()
            if existing.get(record_id)!=digest:pending.append((record_id,digest,text))
        embedded=0
        for start in range(0,len(pending),max(1,batch_size)):
            batch=pending[start:start+max(1,batch_size)]
            if hasattr(self.embedding_adapter,'embed_many'):
                vectors=self.embedding_adapter.embed_many([item[2] for item in batch],timeout_seconds=180)
            else:
                vectors=[self.embedding_adapter.embed(item[2],timeout_seconds=30) for item in batch]
            with self.connect() as c:
                for (record_id,digest,_),vector in zip(batch,vectors):
                    unit=normalized(vector)
                    if len(unit)!=dimensions:continue
                    c.execute('''INSERT OR REPLACE INTO character_corpus_v2_embeddings
                        VALUES (?,?,?,?,?)''',(record_id,model_id,dimensions,digest,json.dumps(unit,separators=(',',':'))))
                    embedded+=1
        return {'embedded':embedded,'enabled':True,'total':len(rows)}

    def import_reviewed_material(self, source=None):
        from domains.persona.reviewed_material import import_material, SOURCE
        return import_material(self, source or SOURCE)

    def import_directory(self,root=None):
        """Use reviewed material by default; explicit JSONL directories remain supported."""
        if root is None:
            return self.import_reviewed_material()
        root = Path(root)
        if root.is_file():
            return self.import_reviewed_material(root)
        material = root / '左然语料候选.json'
        if material.is_file():
            return self.import_reviewed_material(material)
        seen=set();samples=[]
        if not root.is_dir():raise ValueError('corpus_directory_missing')
        for path in sorted(root.rglob('*.jsonl')):
            if 'raw' in path.relative_to(root).parts:continue
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if not line.strip():continue
                data=validate_sample(json.loads(line))
                if data['id'] in seen:raise ValueError('duplicate_corpus_id')
                seen.add(data['id']);samples.append(data)
        self.initialize()
        with self.connect() as c:
            # Only the explicit V2 import scope is replaced; no legacy DB or user data.
            c.execute('DELETE FROM character_corpus_v2');c.execute('DELETE FROM character_corpus_v2_fts')
            for sample in samples:
                body=json.dumps(sample,ensure_ascii=False)
                c.execute('INSERT INTO character_corpus_v2 VALUES (?,?,?,?,?)',(sample['id'],sample['domain'],sample['source_level'],sample['review_status'],body))
                if sample['review_status']=='approved' and sample['source_level']!='runtime_generated':
                    searchable=' '.join([sample['context'],sample['character_logic'],*sample['preferred_direction'],*sample['avoid_direction'],*sample.get('tags',[]),json.dumps(sample.get('behavior',{}),ensure_ascii=False)])
                    c.execute('INSERT INTO character_corpus_v2_fts VALUES (?,?)',(sample['id'],' '.join(sorted(tokens(searchable)))))
        return {'version':2,'records':len(samples),'approved':sum(s['review_status']=='approved' for s in samples)}

    @staticmethod
    def _intent(query, explicit=None):
        # "unified" identifies the chat processing path, not a corpus intent.
        if explicit == 'unified':
            explicit = None
        if explicit and explicit not in {'ordinary', 'simple', 'emotional'}:
            return explicit
        rules = (
            ('distress', r'难过|委屈|焦虑|害怕|不知道.*说|想哭|呜+|撑不住|自责'),
            ('conflict', r'争执|吵架|生气|道歉|边界|不尊重|失望'),
            ('affection', r'想你|喜欢|爱你|撒娇|亲亲|抱抱|亲密'),
            ('planning', r'计划|安排|旅行|休假|去哪|一起|订票|预订'),
            ('fatigue', r'累|疲惫|休息|加班|困|睡'),
            ('initiative', r'主动|联系|报备|到家|位置|分享'),
        )
        return next((name for name, pattern in rules if re.search(pattern, query)), explicit or 'ordinary')

    @staticmethod
    def _intent_fit(text, intent, query=''):
        if intent == 'affection':
            groups = (
                r'想你|想念|思念',
                r'喜欢你|爱你|爱意|恋人',
                r'撒娇|亲密|依赖|靠近|拥抱|抱抱|陪伴',
            )
            query_groups = {index for index, pattern in enumerate(groups) if re.search(pattern, query)}
            text_groups = {index for index, pattern in enumerate(groups) if re.search(pattern, text)}
            return 1 if query_groups & text_groups else -1
        patterns = {
            'distress': r'难过|委屈|焦虑|害怕|受伤|倾诉|表达|开口|安慰|陪伴|自责|情绪',
            'conflict': r'争执|冲突|道歉|边界|尊重|修复|冒犯|分歧|责怪',
            'planning': r'计划|安排|旅行|休假|目的地|偏好|协商|分工|邀请',
            'fatigue': r'疲惫|累|休息|加班|困|睡|放松|调整安排',
            'initiative': r'主动|联系|报备|到达|位置|分享|邀请',
        }
        pattern = patterns.get(intent)
        return 0 if not pattern else 1 if re.search(pattern, text) else -1

    @staticmethod
    def _stage_score(sample, relationship_stage):
        if sample.get('type') == 'reviewed_situational_material':
            return 0
        stage = sample.get('applicability', {}).get('relationship_stage', 'unknown')
        if relationship_stage not in {'established_partner', 'established_partner_in_story'}:
            return 0
        if stage == 'established_partner_in_story':
            return 2.4
        if stage in {'colleagues', 'colleagues_in_story'}:
            return -1.0
        if 'wedding' in stage:
            return -2.0
        return 0

    @staticmethod
    def _appraisal_domains(appraisal):
        goals = (appraisal or {}).get('goal_appraisals', [])
        targets = {item.get('target') for item in goals if isinstance(item, dict)}
        result = set()
        if 'relationship' in targets:
            result.update(('relationship', 'dialogue', 'behavior'))
        if 'user' in targets:
            result.update(('emotion', 'dialogue', 'behavior'))
        if 'libra' in targets:
            result.update(('emotion', 'cognition', 'relationship'))
        if (appraisal or {}).get('standard_appraisals'):
            result.update(('cognition', 'relationship', 'anti_patterns'))
        return result

    def search(self,query,limit=6,domains=None,relationship_stage=None,intent=None,appraisal=None):
        parts=sorted(tokens(query),key=lambda token:(-len(token),token))[:36]
        if not parts and not str(query).strip():return []
        sql='''SELECT c.payload,bm25(character_corpus_v2_fts) AS lexical_rank
            FROM character_corpus_v2_fts f JOIN character_corpus_v2 c ON c.id=f.id
            WHERE character_corpus_v2_fts MATCH ? AND c.review_status='approved' AND c.source_level!='runtime_generated' '''
        params=[' OR '.join('"'+t.replace('"','""')+'"' for t in parts)]
        if domains:
            sql+=' AND c.domain IN ('+','.join('?' for _ in domains)+')';params.extend(domains)
        requested=max(1,min(limit,12));sql+=' ORDER BY lexical_rank LIMIT ?';params.append(max(36,requested*6))
        with self.connect() as c:
            lexical=[] if not parts else [(json.loads(row[0]),row[1],index,0.0)
                  for index,row in enumerate(c.execute(sql,params))]
        dense_scores={}
        if self.embedding_adapter is not None:
            try:
                query_vector=normalized(self.embedding_adapter.embed(query,timeout_seconds=12))
                with self.connect() as c:
                    dense_rows=c.execute('''SELECT e.id,e.vector_json,c.payload FROM character_corpus_v2_embeddings e
                        JOIN character_corpus_v2 c ON c.id=e.id
                        WHERE e.model_id=? AND e.dimensions=? AND c.review_status='approved'
                        AND c.source_level!='runtime_generated' ''',
                        (str(self.embedding_adapter.model_id),int(self.embedding_adapter.dimensions))).fetchall()
                allowed=set(domains or [])
                for record_id,vector_json,payload in dense_rows:
                    sample=json.loads(payload)
                    if allowed and sample.get('domain') not in allowed:continue
                    vector=json.loads(vector_json);score=sum(a*b for a,b in zip(query_vector,vector))
                    if score>=.30:dense_scores[record_id]=(score,sample)
            except (TimeoutError,ValueError,TypeError,sqlite3.Error):
                dense_scores={}
        by_id={sample['id']:(sample,lexical_rank,pos,dense_scores.get(sample['id'],(0,None))[0])
               for sample,lexical_rank,pos,_ in lexical}
        for record_id,(score,sample) in sorted(dense_scores.items(),key=lambda item:item[1][0],reverse=True)[:max(36,requested*6)]:
            by_id.setdefault(record_id,(sample,0.0,999,score))
        rows=list(by_id.values())
        query_tokens={part for part in tokens(query) if len(part)>1}
        resolved_intent=self._intent(query,intent)
        intent_domains={
            'distress': {'emotion','dialogue','relationship','behavior'},
            'emotional': {'emotion','dialogue','relationship','behavior'},
            'conflict': {'relationship','cognition','anti_patterns','behavior'},
            'affection': {'relationship','emotion','dialogue'},
            'planning': {'daily_life','initiative','behavior'},
            'fatigue': {'daily_life','emotion','relationship'},
            'initiative': {'initiative','daily_life','relationship'},
            'action': {'behavior','daily_life','initiative'},
        }.get(resolved_intent,set())
        appraisal_domains=self._appraisal_domains(appraisal)
        def positive_text(pair):
            sample, lexical_rank, lexical_position, dense_score = pair
            behavior=sample.get('behavior') or {}
            return ' '.join([sample.get('context',''),sample.get('character_logic',''),
                *sample.get('preferred_direction',[]),*sample.get('tags',[]),
                behavior.get('trigger',''),*behavior.get('response_options',[])])
        def rank(pair):
            sample, lexical_rank, lexical_position, dense_score = pair
            behavior=sample.get('behavior') or {}
            positive=positive_text(pair)
            positive_tokens={part for part in tokens(positive) if len(part)>1}
            avoid_tokens={part for part in tokens(' '.join(sample.get('avoid_direction',[])+behavior.get('stop_conditions',[]))) if len(part)>1}
            positive_overlap=len(query_tokens & positive_tokens)/max(1,math.sqrt(len(query_tokens)*len(positive_tokens)))
            avoid_only=len((query_tokens & avoid_tokens) - positive_tokens)/max(1,len(query_tokens))
            return (positive_overlap*8
                    +self._stage_score(sample,relationship_stage)
                    +(1.25 if sample.get('domain') in intent_domains else 0)
                    +(.8 if sample.get('domain') in appraisal_domains else 0)
                    +self._intent_fit(positive,resolved_intent,query)*1.5
                    -avoid_only*2
                    +dense_score*3
                    +1/(1+lexical_position))
        if resolved_intent == 'affection':
            rows = [pair for pair in rows if pair[0].get('applicability', {}).get('romance_reference_allowed', True)]
        rows.sort(key=rank,reverse=True)
        intent_matched=[pair for pair in rows if self._intent_fit(positive_text(pair),resolved_intent,query)>0]
        if intent_matched:
            rows=intent_matched
        return [sample for sample,_,_,_ in rows[:requested]]


def format_evidence(samples,budget=5000):
    def shared_history_compatible(value):
        if isinstance(value,str):
            return value.replace(
                '剧情证据不是现实共同经历。',
                '共同历史不代表其中行为正在当前再次发生。',
            )
        if isinstance(value,list):return [shared_history_compatible(item) for item in value]
        if isinstance(value,dict):return {key:shared_history_compatible(item) for key,item in value.items()}
        return value
    selected=[]
    for sample in samples:
        item={k:sample.get(k) for k in ('id','domain','source_level','source_ref','confidence','context','character_logic','preferred_direction','avoid_direction','example_output','applicability','evidence_quote','evidence_line','behavior')}
        if sample.get('type') == 'reviewed_situational_material':
            from domains.persona.reviewed_material import compact_material
            item=compact_material(sample)
        item=shared_history_compatible(item)
        candidate=json.dumps(selected+[item],ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e')
        if len(candidate)<=budget:selected.append(item)
    return ('叙述中的用户指当前用户，左然指你；引用中的人称按说话人理解。情境用于匹配当前话题，反应特点是整理推断，不是必然规则。'
        '同居后和结婚后的感情互动都可供当前婚后关系参考。自身往事和反应可用于理解与表达自己，但不可改成用户亲历。'
        '角色证据区只用于理解与表达，本身不单独证明当前事实或授予行动权限。'
        '若同轮 canonical_shared_history 提供匹配条目，则该条目可以作为双方既定的过去。\n'
        +json.dumps(selected,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e'))
