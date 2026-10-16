"""GA-inspired retrieval: hourly recency + importance + cosine relevance.

The bundled sparse character/word vector is an explicitly reduced test adapter,
not the original semantic embedding model. No private memory imports.
"""
import json

from .clock import utc
from .config import canonical
from .activity_engine import require
from .encoding import lexical as vector, similarity as cosine
from .memory_index import MemoryIndex


def normalize(values):
    if not values:
        return []
    lo, hi = min(values), max(values)
    return [0.5 if hi == lo else (v-lo)/(hi-lo) for v in values]


class LifeMemory:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.index=MemoryIndex(store)
        from .memory_candidates import MemoryCandidates
        self.candidates = MemoryCandidates(store)

    def _records(self,db,ids=None):
        now=self.store.clock.now()
        if ids is not None and not ids:
            return []
        placeholders = ','.join('?' for _ in ids) if ids is not None else ''
        quarantine_filter = (" AND json_extract(body,'$.memory_id') IN (" + placeholders + ')') if ids is not None else ''
        excluded={json.loads(r[0])["memory_id"] for r in db.execute(
            "SELECT body FROM life_evidence WHERE category='cognition' AND kind='memory_quarantine'" + quarantine_filter, ids or [])}
        excluded|=self.index.validity(db,now,ids)
        clause = (' AND id IN (' + ','.join('?' for _ in ids) + ')') if ids is not None else ''
        rows=db.execute('SELECT * FROM life_memories WHERE actor_id=?' + clause + ' ORDER BY created_at,id',
                        (self.store.config['persona']['id'], *(ids or []))).fetchall()
        return [{"id":r[0],"kind":r[1],"description":r[2],"created_at":r[3],"last_accessed":r[4],"importance":r[5],
            "keywords":json.loads(r[6]),"evidence_ids":json.loads(r[7]),"actor_id":r[8],"status":r[9]}
            for r in rows if utc(r[3])<=now and r[0] not in excluded and r[9] in {'observed','inference'}]

    @staticmethod
    def _valid_cached(body,request,records):
        require(body['request']==request,'retrieval id conflict')
        current={r['id']:r for r in records}
        return [r for r in body['memories'] if r['id'] in current and
            all(current[r['id']][k]==r[k] for k in ('description','evidence_ids','actor_id','status'))]

    def retrieve(self,query,retrieval_id,*,keyword_only=False):
        require(isinstance(query,str) and bool(query.strip()),'retrieval query required')
        request={'query':query,'keyword_only':keyword_only};now=self.store.clock.now()
        self.candidates.sync()
        with self.store.connect() as db:
            old=db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_evidence WHERE category=\'memory_retrieval\') AS life_memory_retrievals WHERE id=?',(retrieval_id,)).fetchone()
            if old:
                cached = json.loads(old[0])
                return self._valid_cached(cached,request,self._records(db,[r['id'] for r in cached['memories']]))
            ids = self.candidates.candidates(db, query, self.store.config['persona']['id'], now.isoformat())
            records=self._records(db,ids)
        if keyword_only:
            tokens=set(vector(query))
            records=[r for r in records if tokens.intersection(vector(' '.join(r['keywords'])))]
        # Encoding is outside any database transaction; incoming messages remain writable.
        relevance,index_trace=self.index.score(records,query)
        # Recency/importance must not crowd a matching memory out with wholly
        # unrelated lexical records. With no lexical match retain the context
        # fallback; dense encoders keep their own relevance semantics.
        if index_trace['mode'] == 'lexical' and any(value > 0 for value in relevance):
            matched = [(r, value) for r, value in zip(records, relevance) if value > 0]
            records = [r for r, _ in matched]
            relevance = [value for _, value in matched]
        components={'recency':[self.config['recency_decay_per_hour']**max(0,(now-utc(r['last_accessed'])).total_seconds()/3600) for r in records],
            'importance':[r['importance'] for r in records],'relevance':relevance}
        scaled={k:normalize(v) for k,v in components.items()}
        for i,r in enumerate(records):
            r['scores']={k:scaled[k][i] for k in scaled}
            r['score']=sum(self.config['retrieval_weights'][k]*r['scores'][k] for k in scaled)
        records.sort(key=lambda r:(r['score'],r['created_at'],r['id']),reverse=True)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');current=self._records(db,[r['id'] for r in records])
            old=db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_evidence WHERE category=\'memory_retrieval\') AS life_memory_retrievals WHERE id=?',(retrieval_id,)).fetchone()
            if old:return self._valid_cached(json.loads(old[0]),request,current)
            eligible=self._valid_cached({'request':request,'memories':records},request,current)
            selected=eligible[:self.config['retrieval_count']]
            for r in selected:
                db.execute('UPDATE life_memories SET last_accessed=MAX(last_accessed,?) WHERE id=?',(now.isoformat(),r['id']))
            db.execute("INSERT INTO life_evidence(category,id,body) VALUES('memory_retrieval',?,?)",(retrieval_id,canonical({'request':request,'at':now.isoformat(),
                'memories':selected,'embedding':self.config['embedding'],'actual_index':index_trace,'weights':self.config['retrieval_weights']})))
        return selected


def add_memory(db, memory_id, kind, description, at, importance, keywords, evidence_ids, actor, status):
    db.execute("INSERT INTO life_memories VALUES(?,?,?,?,?,?,?,?,?,?)", (
        memory_id, kind, description, at, at, importance, canonical(keywords),
        canonical(evidence_ids), actor, status))
