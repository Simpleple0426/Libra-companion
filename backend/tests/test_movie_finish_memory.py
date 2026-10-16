"""Explicit shared viewing completion must survive retries without LLM scoring."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from application.movie_room import MovieRoom
from domains.memory.store import MemoryStore


class MovieFinishMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'isolated.db'
        self.connections = []
        self.store = MemoryStore(self.path)
        self.store.initialize()
        with self.connect() as db:
            db.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY,source TEXT,created_at TEXT,role TEXT,content TEXT)')
        self.room = MovieRoom(self.connect, memory_store=self.store)
        self.room.start({'id': 'view-1', 'title': '测试电影'})

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        self.connections.append(db)
        return db

    def tearDown(self):
        for db in self.connections:
            db.close()
        self.tmp.cleanup()

    def test_finish_creates_named_shared_memory_without_chat(self):
        self.room.control('view-1', 'finish')
        with self.connect() as db:
            row = db.execute('SELECT * FROM lmc_memories').fetchone()
            self.assertEqual(row['primary_scope'], 'shared')
            self.assertEqual(row['record_status'], 'active')
            self.assertIn('测试电影', row['content'])
            self.assertIn('用户已标记', row['content'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lmc_sources').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lmc_search_documents').fetchone()[0], 1)

    def test_repeated_finish_and_restart_do_not_duplicate_or_change_date(self):
        self.room.control('view-1', 'finish')
        first = self.room.get('view-1')['updated_at']
        self.room = MovieRoom(self.connect, memory_store=self.store)
        self.room.control('view-1', 'finish')
        self.assertEqual(first, self.room.get('view-1')['updated_at'])
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lmc_memories').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM raw_experiences').fetchone()[0], 1)

    def test_pause_stop_and_restart_do_not_create_completion_memory(self):
        self.room.control('view-1', 'pause')
        self.room.control('view-1', 'stop')
        self.room = MovieRoom(self.connect, memory_store=self.store)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lmc_memories').fetchone()[0], 0)

    def test_memory_failure_rolls_back_completion_and_can_retry(self):
        with patch.object(self.store, '_write_candidate', side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):
                self.room.control('view-1', 'finish')
        self.assertEqual(self.room.get('view-1')['status'], 'watching')
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM raw_experiences').fetchone()[0], 0)
        self.room.control('view-1', 'finish')
        self.assertEqual(self.room.get('view-1')['status'], 'completed')

    def test_discussion_saved_with_sources_and_retry_deduplicated(self):
        self.room.control('view-1', 'finish')
        messages = [{'id': 1, 'role': 'user', 'content': '这次没有哭。', 'created_at': '2026-10-08T12:00:00+08:00'}]
        items = [{'text': '用户表示这次观看没有哭。', 'evidence': [{'message_id': 1, 'quote': '这次没有哭。'}]}]
        self.room.discussion_result('view-1', items, messages)
        self.room.discussion_result('view-1', items, messages)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lmc_memories').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lmc_sources').fetchone()[0], 3)
        self.assertEqual(self.room.get('view-1')['discussion_status'], 'ready')

    def test_checkin_recollects_named_shared_event_without_search_words(self):
        self.room.control('view-1', 'finish')
        with self.connect() as db:
            db.execute("UPDATE lmc_event_context SET occurred_start='2026-09-01T12:00:00+00:00'")
        packet = self.store.recollect('session', [], now='2026-12-01T12:00:00+00:00')
        self.assertEqual(len(packet['memories']), 1)
        self.assertEqual(packet['memories'][0]['primary_scope'], 'shared')
        self.assertIn('测试电影', packet['memories'][0]['content'])
        self.assertEqual(self.store.recollect('session', [], now='2026-12-01T13:00:00+00:00')['memories'], [])
        self.assertEqual(self.store.recollect('session', [], now='2026-12-02T12:00:00+00:00')['memories'], [])

    def test_checkin_excludes_invalid_sources(self):
        self.room.control('view-1', 'finish')
        with self.connect() as db:
            db.execute("UPDATE lmc_event_context SET occurred_start='2026-09-01T12:00:00+00:00'")
            db.execute("UPDATE raw_experiences SET source_status='invalid'")
        self.assertEqual(self.store.recollect('session', [], now='2026-12-01T12:00:00+00:00')['memories'], [])


if __name__ == '__main__':
    unittest.main()
