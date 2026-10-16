from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from application.reminders import initialize, settings, manage, deliver_one, cancel


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.db'
        with self.connect() as c:
            c.executescript('''CREATE TABLE todos(local_id TEXT PRIMARY KEY,title TEXT,due_date TEXT,done INTEGER,updated_at TEXT);
              CREATE TABLE messages(id INTEGER PRIMARY KEY,role TEXT,content TEXT,created_at TEXT,source TEXT,message_type TEXT);
              INSERT INTO messages(id,role,content) VALUES(1,'user','明天三点提醒我交材料');''')
            initialize(c)
            c.commit()

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def seed(self, repeat=None):
        with self.connect() as c:
            c.execute("INSERT INTO todos VALUES('one','交材料','2026-10-14T15:00:00',0,'now')")
            settings(c, dict(local_id='one', remind_at='2026-10-14T15:00:00', repeat_rule=repeat))

    def test_due_once_and_does_not_complete_task(self):
        self.seed()
        pushed = []
        now = datetime(2026, 10, 14, 15)
        self.assertTrue(deliver_one(self.connect, lambda *args: '提醒', pushed.extend, now))
        self.assertFalse(deliver_one(self.connect, lambda *args: '重复', pushed.extend, now))
        with self.connect() as c:
            self.assertEqual(c.execute('select done from todos').fetchone()[0], 0)
        self.assertEqual(len(pushed), 1)

    def test_cancel_or_complete_during_generation_prevents_delivery(self):
        self.seed()
        def generate(*args):
            with self.connect() as c:
                cancel(c, 'one')
            return '不得发送'
        self.assertFalse(deliver_one(self.connect, generate, lambda *_: self.fail(), datetime(2026,10,14,15)))

    def test_repeat_request_is_saved_as_one_off(self):
        self.seed('weekly')
        with self.connect() as c:
            self.assertIsNone(c.execute('select repeat_rule from todo_reminders').fetchone()[0])
        now = datetime(2026,10,14,15)
        self.assertTrue(deliver_one(self.connect, lambda *args: None, lambda *_: None, now))
        self.assertFalse(deliver_one(self.connect, lambda *args: None, lambda *_: None, datetime(2026,10,21,15)))

    def test_old_client_preserves_reminder_time(self):
        self.seed()
        with self.connect() as c:
            settings(c, {'local_id': 'one'})
            self.assertEqual(c.execute('select remind_at from todo_reminders').fetchone()[0], '2026-10-14T15:00:00')

    def test_proactive_cannot_create_user_reminder(self):
        with self.connect() as c, self.assertRaises(ValueError):
            manage(c, json.dumps({'operation':'create'}), {'agentic_proactive':True})

    def test_arrangement_without_reminder_stays_unarmed(self):
        with self.connect() as c:
            result = manage(c, json.dumps({'operation':'create','title':'组会','due_date':'2099-10-14T00:00:00',
                'evidence_quote':'明天三点提醒我交材料'}), {'current_event':{'message_id':1}})
            self.assertEqual(result['status'], 'completed')
            self.assertIsNone(c.execute('select remind_at from todo_reminders').fetchone()[0])
