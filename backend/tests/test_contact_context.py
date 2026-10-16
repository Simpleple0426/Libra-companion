import sqlite3
import unittest
from application.contact_context import recent_messages, reporting_evidence


class ContactContextTests(unittest.TestCase):
    def test_recent_window_preserves_roles_time_and_order(self):
        messages = [{'id': i, 'role': 'user' if i % 2 else 'assistant', 'content': str(i),
                     'created_at': str(i), 'source': 'chat', 'media_url': 'unused'} for i in range(30)]
        result = recent_messages(messages)
        self.assertEqual([r['id'] for r in result], list(range(10, 30)))
        self.assertEqual(result[-1]['role'], 'user')
        self.assertEqual(result[-1]['created_at'], '29')
        self.assertNotIn('media_url', result[-1])

    def test_old_request_and_cancellation_survive_recent_window(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE messages(id INTEGER,role TEXT,content TEXT,created_at TEXT,source TEXT)')
        db.executemany('INSERT INTO messages VALUES(?,?,?,?,?)',
                       [(1, 'user', '到律所说一声', '1', 'chat'),
                        (2, 'assistant', '好，到了告诉你', '2', 'chat'),
                        (3, 'user', '不用报备了', '3', 'chat')]
                       + [(i, 'user', '普通聊天', str(i), 'chat') for i in range(4, 40)]
                       + [(40, 'user', '到律所告诉我', '40', 'movie_chat')])
        evidence = reporting_evidence(lambda: db)
        self.assertIn('到律所说一声', [r['content'] for r in evidence])
        self.assertIn('不用报备了', [r['content'] for r in evidence])
        self.assertNotIn(40, [r['id'] for r in evidence])
        self.assertLessEqual(len(evidence), 12)
