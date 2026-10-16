"""Versioned derived index, original memories/evidence remain authoritative."""
import json
from .clock import utc
from .config import canonical,digest
from .encoding import LexicalEncoder,CachedLocalEncoder,similarity

class MemoryIndex:
    def __init__(self,store,encoder=None):
        self.store=store;self.encoder=encoder
        with store.connect() as db:
            db.executescript('\n            CREATE TABLE IF NOT EXISTS life_memory_index(memory_id TEXT,encoder_id TEXT,text_hash TEXT,body TEXT NOT NULL,\n              PRIMARY KEY(memory_id,encoder_id,text_hash));\n            CREATE TABLE IF NOT EXISTS life_memory_validity(id TEXT PRIMARY KEY,memory_id TEXT NOT NULL,body TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS life_memory_validity_by_memory ON life_memory_validity(memory_id)')
    def configure(self,encoder):
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO life_state(name,id,body) VALUES('encoder',1,?)",(canonical(encoder.descriptor),))
        self.encoder=encoder
    def configured(self):
        with self.store.connect() as db:r=db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'encoder\') AS life_encoder').fetchone()
        return json.loads(r[0]) if r else LexicalEncoder.descriptor
    def _encoder(self):
        if self.encoder:return self.encoder
        d=self.configured()
        self.encoder=CachedLocalEncoder(d) if d['mode']=='semantic' else LexicalEncoder()
        return self.encoder
    def validity(self,db,now,ids=None):
        values={}
        if ids is not None and not ids:return set()
        clause = (' WHERE memory_id IN (' + ','.join('?' for _ in ids) + ')') if ids is not None else ''
        for ident,mid,raw in db.execute('SELECT * FROM life_memory_validity' + clause + ' ORDER BY rowid', ids or []):
            body=json.loads(raw)
            if utc(body['effective_at'])<=now:values[mid]=body
        return {mid for mid,v in values.items() if v['status']=='revoked' or
                v.get('valid_until') and utc(v['valid_until'])<=now}
    def mark(self,review_id,memory_id,*,effective_at,status,reason,valid_until=None):
        if status not in {'current','revoked'} or not reason.strip():raise ValueError('explicit validity review required')
        body={'effective_at':utc(effective_at).isoformat(),'status':status,'reason':reason,
              'valid_until':utc(valid_until).isoformat() if valid_until else None,'source':'explicit_isolated_validity_review'}
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM life_memories WHERE id=?',(memory_id,)).fetchone():raise ValueError('unknown memory')
            old=db.execute('SELECT memory_id,body FROM life_memory_validity WHERE id=?',(review_id,)).fetchone()
            if old and old!=(memory_id,canonical(body)):raise ValueError('validity review conflict')
            if not old:
                db.execute('INSERT INTO life_memory_validity VALUES(?,?,?)',(review_id,memory_id,canonical(body)))
                # Invalidate model contexts prepared against previous eligible evidence.
                meta=json.loads(db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'cognition\') AS life_cognition_state').fetchone()[0]);meta['revision']+=1
                db.execute("UPDATE life_state SET body=? WHERE name='cognition'",(canonical(meta),))
    def vectors(self,records,encoder):
        descriptor=encoder.descriptor;eid=digest(descriptor);out={};pending=[]
        with self.store.connect() as db:
            for r in records:
                th=digest(r['description'])
                old=db.execute('SELECT body FROM life_memory_index WHERE memory_id=? AND encoder_id=? AND text_hash=?',(r['id'],eid,th)).fetchone()
                body=json.loads(old[0]) if old else None
                if body and body['status']=='ready' and body['evidence_ids']==r['evidence_ids']:out[r['id']]=body['vector']
                else:
                    if body and body.get('retry_after') and utc(body['retry_after'])>self.store.clock.now():
                        raise RuntimeError('encoder index retry deferred: '+body.get('error','unknown'))
                    body={'status':'pending','encoder':descriptor,'text_hash':th,'evidence_ids':r['evidence_ids'],
                          'created_at':r['created_at'],'actor_id':r['actor_id'],'vector':None,
                          'prior_failure':body.get('error') if body else None}
                    db.execute('INSERT OR REPLACE INTO life_memory_index VALUES(?,?,?,?)',(r['id'],eid,th,canonical(body)))
                    pending.append((r,body))
        if pending:
            try:
                encoded=encoder.encode([r['description'] for r,b in pending])
                if len(encoded)!=len(pending):raise ValueError('encoder count mismatch')
                if descriptor['mode']=='semantic':
                    from .encoding import validate_vectors
                    encoded=validate_vectors(encoded,len(pending),descriptor['dimensions'])
                with self.store.connect() as db:
                    for (r,body),v in zip(pending,encoded):
                        body.update(status='ready',vector=v);out[r['id']]=v
                        db.execute('UPDATE life_memory_index SET body=? WHERE memory_id=? AND encoder_id=? AND text_hash=?',
                            (canonical(body),r['id'],eid,body['text_hash']))
            except Exception as exc:
                from datetime import timedelta
                with self.store.connect() as db:
                    for r,body in pending:
                        body.update(status='failed',error=type(exc).__name__+': '+str(exc),
                            retry_after=(self.store.clock.now()+timedelta(seconds=300)).isoformat(),
                            retry_policy='project_test_default_300_seconds')
                        db.execute('UPDATE life_memory_index SET body=? WHERE memory_id=? AND encoder_id=? AND text_hash=?',
                            (canonical(body),r['id'],eid,body['text_hash']))
                raise
        return out
    def score(self,records,query):
        try:
            enc=self._encoder();v=self.vectors(records,enc);q=enc.encode([query])[0]
            if enc.descriptor['mode']=='semantic':
                from .encoding import validate_vectors
                q=validate_vectors([q],1,enc.descriptor['dimensions'])[0]
            return [similarity(q,v[r['id']]) for r in records],{'mode':enc.descriptor['mode'],'encoder':enc.descriptor,'degraded':False}
        except Exception as exc:
            enc=LexicalEncoder();v=self.vectors(records,enc);q=enc.encode([query])[0]
            return [similarity(q,v[r['id']]) for r in records],{'mode':'lexical','encoder':enc.descriptor,
                'degraded':True,'requested_encoder':self.encoder.descriptor if self.encoder else self.configured(),
                'reason':type(exc).__name__+': '+str(exc)}
