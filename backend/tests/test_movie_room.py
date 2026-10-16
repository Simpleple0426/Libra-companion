import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime

from application.movie_room import MovieRoom
from infrastructure.sqlite import database
from infrastructure.sqlite import content_repository as chat


class MovieRoomTests(unittest.TestCase):
    def setUp(self):
        self.connections = []
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'core.db'
        with self.connect() as db:
            db.executescript('''CREATE TABLE messages(id INTEGER PRIMARY KEY,role TEXT,content TEXT,created_at TEXT,source TEXT,message_type TEXT DEFAULT 'text',media_url TEXT,duration_seconds REAL);
                CREATE TABLE favorite_messages(message_id INTEGER PRIMARY KEY,created_at TEXT);
                CREATE TABLE cognition_inputs(message_id INTEGER,request_key TEXT);''')
        self.room = MovieRoom(self.connect)
        self.room.start({'id': 'view-1', 'title': '测试影片'})
        for source in ['chat', 'movie_watch', 'movie_chat']:
            with self.connect() as db:
                db.execute("INSERT INTO messages(role,content,created_at,source) VALUES('assistant','共同关键词','2026-09-30T12:00:00',?)", (source,))
                db.execute("INSERT INTO favorite_messages VALUES(last_insert_rowid(),'2026-09-30T12:00:00')")

    def tearDown(self):
        for db in self.connections:
            db.close()
        self.tmp.cleanup()

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        self.connections.append(db)
        return db

    def test_main_chat_history_updates_search_and_favorites_exclude_movie(self):
        with patch.object(chat, 'get_connection', self.connect):
            readers = [lambda: chat.get_messages(), lambda: chat.get_messages_after(0),
                lambda: chat.get_message_updates_after(0), lambda: chat.get_messages_for_date('2026-09-30'),
                lambda: chat.get_messages_between(datetime(2026,9,30), datetime(2026,10,1)),
                lambda: chat.search_messages('共同'), lambda: chat.get_favorite_messages()]
            for read in readers:
                rows = read()
                self.assertEqual([r['source'] for r in rows], ['chat'])
        self.assertEqual([r['source'] for r in self.room.messages('2026-09-30')], ['movie_watch', 'movie_chat'])

    def test_day_search_and_pagination(self):
        rows = self.room.messages('2026-09-30', limit=1)
        self.assertEqual(len(rows), 1)
        older = self.room.messages('2026-09-30', before=rows[0]['id'])
        self.assertEqual(len(older), 1)
        self.assertEqual(self.room.messages('2026-09-29'), [])

    def test_quote_must_be_verbatim_in_received_subtitles(self):
        class Replies(list):
            payload = {'watch_quotes': [{'text': '真实短句', 'thought': '感触'}, {'text': '编造台词', 'thought': '不能存'}]}
        snapshot = {'id': 'view-1', 'subtitles': [{'start': 10, 'text': '这里有真实短句。'}]}
        self.room.record(snapshot, '剧情', Replies(), [{'id': 2}])
        self.room.record(snapshot, '剧情', Replies(), [{'id': 2}])
        movie = self.room.get('view-1')
        self.assertEqual([q['text'] for q in movie['quotes']], ['真实短句'])
        self.assertEqual(self.room.messages()[0]['viewing_id'], 'view-1')

    def test_stop_is_not_finish_and_review_is_idempotent(self):
        self.room.control('view-1', 'stop')
        self.assertFalse(self.room.claim_review('view-1'))
        self.room.control('view-1', 'finish')
        self.assertTrue(self.room.claim_review('view-1'))
        self.assertFalse(self.room.claim_review('view-1'))
        self.room.review_result('view-1', '影评')
        self.assertFalse(self.room.claim_review('view-1'))

    def test_chat_request_retry_does_not_duplicate_user_message(self):
        def save(role, content, source, connection):
            return connection.execute('INSERT INTO messages(role,content,source,created_at) VALUES(?,?,?,?)',
                                      (role, content, source, '2026-09-30T12:00:00')).lastrowid
        first = self.room.accept_chat('request', '你好', 'view-1', save)
        again = self.room.accept_chat('request', '你好', 'view-1', save)
        self.assertEqual(first['message_id'], again['message_id'])
        with self.assertRaises(ValueError):
            self.room.accept_chat('request', '别的内容', 'view-1', save)

    def test_restart_recovers_review_and_preserves_movies(self):
        self.room.control('view-1', 'finish')
        self.room.claim_review('view-1')
        restored = MovieRoom(self.connect)
        self.assertEqual(restored.get('view-1')['review_status'], 'error')

    def test_receipt_sync_independent_of_history_date(self):
        from app.api.movie_room import build_movie_router
        from types import SimpleNamespace
        def save(role, content, source, connection):
            return connection.execute("INSERT INTO messages(role,content,source,created_at) VALUES(?,?,?,'2026-09-30T12:00:00')", (role,content,source)).lastrowid
        accepted = self.room.accept_chat('recover', 'hello', 'view-1', save)
        router = build_movie_router(self.room, SimpleNamespace(current=lambda: None), lambda: [], None, None)
        endpoint = next(route.endpoint for route in router.routes if route.path.endswith('/messages'))
        pending = endpoint(date='2026-09-29', request_id='recover', before=None, limit=100)
        self.assertEqual(pending['messages'], [])
        self.assertFalse(pending['request_state']['completed'])
        self.assertEqual(pending['request_state']['messages'][0]['id'], accepted['message_id'])
        self.room.finish_chat('recover', 'view-1', [{'id': 999, 'role': 'assistant', 'content': 'reply'}])
        completed = endpoint(date='2026-09-29', request_id='recover', before=None, limit=100)
        self.assertTrue(completed['request_state']['completed'])
        self.assertEqual(len(completed['request_state']['messages']), 2)
