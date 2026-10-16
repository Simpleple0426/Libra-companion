"""Incremental local full-text shortlist; original memories stay authoritative."""
import json

from .encoding import lexical


LIMIT = 256


def terms(text):
    # Stable ASCII tokens preserve Chinese character/bigram boundaries in FTS5.
    return ['t' + token.encode('utf8').hex() for token in lexical(text)]


class MemoryCandidates:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS life_memory_fts USING fts5(memory_id UNINDEXED,tokens)')
            db.execute('CREATE TABLE IF NOT EXISTS life_memory_search_dirty(id TEXT PRIMARY KEY)')
            db.execute('CREATE TABLE IF NOT EXISTS life_memory_search_ids(id TEXT PRIMARY KEY,fts_rowid INTEGER UNIQUE)')
            db.execute('CREATE TABLE IF NOT EXISTS life_memory_search_meta(version INTEGER PRIMARY KEY)')
            db.execute('''CREATE INDEX IF NOT EXISTS life_memory_quarantine_id
                ON life_evidence(json_extract(body,'$.memory_id'))
                WHERE category='cognition' AND kind='memory_quarantine' ''')
            for event, ref in (('INSERT', 'new'), ('UPDATE', 'new'), ('DELETE', 'old')):
                fields = ' OF description,keywords,actor_id,status' if event == 'UPDATE' else ''
                db.execute(f'''CREATE TRIGGER IF NOT EXISTS life_memory_search_{event.lower()}
                    AFTER {event}{fields} ON life_memories BEGIN
                    INSERT OR IGNORE INTO life_memory_search_dirty VALUES({ref}.id); END''')
            for column in ('created_at', 'last_accessed', 'importance'):
                db.execute(f'CREATE INDEX IF NOT EXISTS life_memories_by_{column} ON life_memories(actor_id,{column} DESC,id)')
            if not db.execute('SELECT 1 FROM life_memory_search_meta WHERE version=1').fetchone():
                db.execute('INSERT OR IGNORE INTO life_memory_search_dirty SELECT id FROM life_memories')
                db.execute('INSERT INTO life_memory_search_meta VALUES(1)')

    def sync(self):
        # Small transactions allow chat/state writers between batches. Trigger
        # rows and index changes commit atomically, including crash recovery.
        while True:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                pending = db.execute('SELECT id FROM life_memory_search_dirty LIMIT 256').fetchall()
                if not pending:
                    return
                for ident, in pending:
                    row = db.execute('SELECT description,keywords FROM life_memories WHERE id=?', (ident,)).fetchone()
                    indexed = db.execute('SELECT fts_rowid FROM life_memory_search_ids WHERE id=?', (ident,)).fetchone()
                    if indexed:
                        db.execute('DELETE FROM life_memory_fts WHERE rowid=?', indexed)
                        db.execute('DELETE FROM life_memory_search_ids WHERE id=?', (ident,))
                    if row:
                        tokens = terms(row[0] + ' ' + ' '.join(json.loads(row[1])))
                        inserted = db.execute('INSERT INTO life_memory_fts VALUES(?,?)', (ident, ' '.join(tokens)))
                        db.execute('INSERT INTO life_memory_search_ids VALUES(?,?)', (ident, inserted.lastrowid))
                    db.execute('DELETE FROM life_memory_search_dirty WHERE id=?', (ident,))

    def candidates(self, db, query, actor, now):
        tokens = terms(query)[:240]
        ids = set()
        # Exclude invalid evidence before LIMIT so a large revoked cluster
        # cannot crowd out an older valid match.
        eligible = '''NOT EXISTS(SELECT 1 FROM life_evidence e
            WHERE e.category='cognition' AND e.kind='memory_quarantine'
              AND json_extract(e.body,'$.memory_id')=m.id)
            AND NOT EXISTS(SELECT 1 FROM life_memory_validity v WHERE v.memory_id=m.id
              AND v.rowid=(SELECT MAX(v2.rowid) FROM life_memory_validity v2
                  WHERE v2.memory_id=m.id AND json_extract(v2.body,'$.effective_at')<=?)
              AND (json_extract(v.body,'$.status')='revoked'
                   OR json_extract(v.body,'$.valid_until')<=?))'''
        if tokens:
            rows = db.execute('''SELECT f.memory_id FROM life_memory_fts f
                JOIN life_memories m ON m.id=f.memory_id
                WHERE life_memory_fts MATCH ? AND m.actor_id=? AND m.created_at<=?
                AND m.status IN ('observed','inference') AND ''' + eligible + ' ORDER BY rank LIMIT ?',
                              (' OR '.join(tokens), actor, now, now, now, LIMIT)).fetchall()
            ids.update(r[0] for r in rows)
        # Retain recent/important context even when the query uses new wording.
        for column in ('last_accessed', 'importance'):
            ids.update(r[0] for r in db.execute(f'''SELECT m.id FROM life_memories m
                WHERE m.actor_id=? AND m.created_at<=? AND m.status IN ('observed','inference')
                AND {eligible} ORDER BY m.{column} DESC,m.id LIMIT 64''', (actor, now, now, now)))
        return sorted(ids)
