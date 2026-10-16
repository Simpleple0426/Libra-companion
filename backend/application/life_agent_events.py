"""Durable life-to-chat delivery, independent of the UI's bounded activity feed."""
import json

from life_prototype.activity_feed import read
from application.life_agent_mailbox import connect


def _facts(engine):
    state = engine.p.snapshot()
    with engine.store.connect() as db:
        # Display text is not a delivery identity: separate committed edits
        # can have the same summary. The outbox deduplicates by source ID.
        items = read(db, state, engine.p.config, limit=None, collapse_consecutive=False)
        for ident, status, receipt in db.execute(
                "SELECT message_id,status,receipt FROM life_agenda_messages WHERE status IN ('clarify','needs_review','expired')"):
            result = json.loads(receipt) if receipt else {}
            items.append({'id': 'agenda-review:' + status + ':' + ident, 'kind': 'agenda_' + status,
                'event': '日程请求需要说明或澄清',
                'occurred_at': result.get('at') or engine.clock.now().isoformat(),
                'summary_source': 'committed_agenda_receipt',
                'detail': {'source_message': ident, 'status': status, 'receipt': result,
                           'semantics': 'schedule_not_changed'}})
    with connect(engine) as db:
        for ident, status, receipt, received_at in db.execute(
                "SELECT id,status,receipt,received_at FROM life_agent_inbox WHERE status IN ('failed','expired')"):
            items.append({'id': 'life-input:' + ident, 'kind': 'life_input_' + status,
                'event': '生活请求未执行', 'occurred_at': received_at or engine.clock.now().isoformat(),
                'summary_source': 'committed_delivery_receipt',
                'detail': {'source_message': ident, 'status': status,
                           'receipt': json.loads(receipt) if receipt else None}})
    return items


def initialize(engine):
    with connect(engine) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS life_agent_outbox(
            id TEXT PRIMARY KEY, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT)""")
        ready = db.execute("SELECT 1 FROM mailbox_meta WHERE key='outbox_initialized'").fetchone()
    if not ready:
        with engine.store.connect() as db:
            old = db.execute("SELECT 1 FROM sqlite_master WHERE name='life_agent_outbox'").fetchone()
            rows = db.execute('SELECT id,body,status,attempts,last_error FROM life_agent_outbox').fetchall() if old else []
        facts = _facts(engine)
        with connect(engine) as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT 1 FROM life_agent_outbox LIMIT 1').fetchone()
            db.executemany('INSERT OR IGNORE INTO life_agent_outbox VALUES(?,?,?,?,?)', rows)
            _insert_facts(db, facts, historical=not (old or existing))
            # The migration, baseline and marker commit together. Merely
            # finding the table does not mean initialization completed.
            db.execute("INSERT OR IGNORE INTO mailbox_meta VALUES('outbox_initialized')")
    else:
        capture(engine)


def _insert_facts(db, facts, *, historical=False):
    for item in facts:
        db.execute('INSERT OR IGNORE INTO life_agent_outbox(id,body,status) VALUES(?,?,?)',
                   (item['id'], json.dumps(item, ensure_ascii=False), 'historical' if historical else 'pending'))


def capture(engine, *, historical=False):
    facts = _facts(engine)
    with connect(engine) as db:
        _insert_facts(db, facts, historical=historical)


def pending(engine, limit=1):
    with connect(engine) as db:
        rows = db.execute("SELECT body FROM life_agent_outbox WHERE status='pending' ORDER BY attempts,rowid LIMIT ?",
                          (limit,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def acknowledge(engine, ident, outcome):
    with connect(engine) as db:
        db.execute("UPDATE life_agent_outbox SET status=?, attempts=attempts+1,last_error=? WHERE id=? AND status='pending'",
                   ('pending' if outcome.startswith('failed') else 'delivered',
                    outcome if outcome.startswith('failed') else None, ident))
