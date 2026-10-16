"""Delivery identities must survive display compaction and repeated capture."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from application import life_agent_events as events, life_agent_mailbox as mailbox
from life_prototype.activity_feed import read


class Store:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            yield db
            db.commit()
        finally:
            db.close()


class LifeAgentEventsTests(unittest.TestCase):
    def test_identical_summaries_deliver_each_commit_once(self):
        for kind in ('agenda', 'companion'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory) / 'life.sqlite3')
                engine = SimpleNamespace(store=store,
                    p=SimpleNamespace(snapshot=lambda: {}, config={}))
                with store.connect() as db:
                    db.execute('CREATE TABLE events (id TEXT, occurred_at TEXT, description TEXT, '
                               'kind TEXT, activity_id TEXT, coarse_plan_id TEXT, fine_plan_id TEXT)')
                    db.execute('CREATE TABLE life_agenda_messages '
                               '(message_id TEXT, status TEXT, receipt TEXT)')
                mailbox.initialize(engine)
                events.initialize(engine)
                ids = []
                for index in range(2):
                    ident = str(index)
                    at = f'2026-09-30T16:0{index}:00+08:00'
                    with store.connect() as db:
                        if kind == 'agenda':
                            db.execute('INSERT INTO life_agenda_messages VALUES (?,?,?)',
                                       (ident, 'applied', json.dumps({'at': at})))
                            ids.append('agenda-review:' + ident)
                        else:
                            ids.append('companion-message:' + ident)
                            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)',
                                       (ids[-1], at, 'Same ongoing companionship',
                                        'companion_update', None, None, None))
                    events.capture(engine)
                    self.assertEqual([e['id'] for e in events.pending(engine, 100)], ids)
                with store.connect() as db:
                    self.assertEqual([e['id'] for e in read(db, {}, {}, limit=None)], ids[:1])
                # Rescanning and reopening never enqueue a delivered ID again.
                events.acknowledge(engine, ids[0], 'delivered')
                events.capture(engine)
                events.initialize(engine)
                self.assertEqual([e['id'] for e in events.pending(engine, 100)], ids[1:])
                events.acknowledge(engine, ids[1], 'delivered')
                events.initialize(engine)
                self.assertEqual(events.pending(engine, 100), [])
                with mailbox.connect(engine) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM life_agent_outbox').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
