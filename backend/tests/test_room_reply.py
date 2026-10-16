import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from application.room_reply import generate, MusicRoomChat
from application.movie_room import MovieRoom
from application.movie_room_agent import MovieAgent
from domains.memory.ingestion import MemoryIngestionMixin


class RoomReplyTests(unittest.TestCase):
    def setUp(self):
        self.connections = []
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.db'
        with self.connect() as db:
            db.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY, role TEXT, content TEXT, source TEXT, created_at TEXT)')
            db.executescript((Path(__file__).parents[1] / 'domains/memory/source_schema.sql').read_text(encoding='utf-8'))
            db.execute("INSERT INTO memory_config VALUES('main_thread_id','original-session')")
        self.runtime = {
            'memory_store': MemoryIngestionMixin(),
            'get_connection': self.connect, 'save_message': self.save,
            'codex_lock': threading.Lock(), 'current_thread_id': 'original-session',
            'CHAT_MODEL': 'test', '_record_llm_usage': Mock(),
            '_parse_json_object': json.loads,
            '_parse_reply_messages': lambda text: json.loads(text)['messages'],
            'run_cli': Mock(return_value=SimpleNamespace(
                session_id='original-session', text='{"messages":["一起听吧"]}')),
            '_prepare_generation_turn': Mock(side_effect=AssertionError('heavy path')),
            'load_persona_bundle': Mock(side_effect=AssertionError('persona injection')),
        }

    def tearDown(self):
        for db in self.connections:
            db.close()
        self.tmp.cleanup()

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        self.connections.append(db)
        return db

    def save(self, role, content, source, connection):
        return connection.execute('INSERT INTO messages(role,content,source,created_at) VALUES(?,?,?,?)',
                                  (role, content, source, '2026-09-30')).lastrowid

    def test_shared_session_without_cognition_or_persona(self):
        replies, identity = generate(self.runtime, '一起看电影', 'movie_watch')
        self.assertEqual(identity, 'original-session')
        self.runtime['run_cli'].assert_called_once_with('一起看电影', session_id=identity, image_paths=None, model='test')
        self.assertEqual(replies[:1].payload, {'messages': ['一起听吧']})
        self.runtime['_prepare_generation_turn'].assert_not_called()
        self.runtime['load_persona_bundle'].assert_not_called()

    def test_never_creates_or_replaces_main_thread(self):
        self.runtime['current_thread_id'] = None
        with self.assertRaises(RuntimeError):
            generate(self.runtime, 'room', 'music_room')
        self.runtime['run_cli'].assert_not_called()
        self.runtime['current_thread_id'] = 'original-session'
        self.runtime['run_cli'].return_value.session_id = 'unexpected'
        with self.assertRaises(RuntimeError):
            generate(self.runtime, 'room', 'music_room')
        self.assertEqual(self.runtime['current_thread_id'], 'original-session')

    def test_music_retry_returns_receipt_and_context_source(self):
        service = MusicRoomChat(self.runtime)
        request = SimpleNamespace(request_id='one', message='喜欢吗', music_context='正在播放：测试歌曲')
        first = service.chat(request)
        self.assertEqual(service.chat(request), first)
        self.runtime['run_cli'].assert_called_once()
        self.assertIn('测试歌曲', self.runtime['run_cli'].call_args.args[0])
        with self.connect() as db:
            rows = db.execute('SELECT * FROM messages').fetchall()
            raws = db.execute('SELECT * FROM raw_experiences').fetchall()
            self.assertEqual(db.execute('SELECT count(*) FROM memory_jobs').fetchone()[0], 1)
        self.assertEqual([r['source_system'] for r in raws], ['libra_music_room'] * 2)
        self.assertEqual([r['segmented'] for r in raws], [1, 1])
        self.assertEqual([r['thread_id'] for r in raws], ['original-session'] * 2)
        self.assertIn('测试歌曲', raws[0]['metadata_json'])
        self.assertEqual([r['source'] for r in rows], ['music_room', 'music_room'])
        self.assertEqual(first['reply_messages'][0]['id'], rows[1]['id'])
        request.message = 'different'
        with self.assertRaises(ValueError):
            service.chat(request)

    def test_movie_retry_and_atomic_reply_commit(self):
        records = MovieRoom(self.connect)
        records.start({'id': 'view', 'title': '电影'})
        service = MovieAgent(self.runtime, records, SimpleNamespace(current=lambda: {'id': 'view'}))
        request = SimpleNamespace(request_id='one', message='这一幕', viewing_id=None)
        with self.connect() as db:
            db.execute("CREATE TRIGGER fail_receipt BEFORE UPDATE OF replies ON movie_chat_requests BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            service.chat(request)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM messages').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM raw_experiences').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM memory_jobs').fetchone()[0], 0)
            db.execute('DROP TRIGGER fail_receipt')
        result = service.chat(request)
        self.assertEqual(service.chat(request), result)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM messages').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT count(*) FROM memory_jobs').fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM raw_experiences WHERE source_system='libra_movie_room'").fetchone()[0], 2)
        self.assertEqual(records.messages()[-1]['viewing_id'], 'view')

    def test_room_journal_dedup_and_media_rejection(self):
        from domains.memory.base import ValidationError
        store = self.runtime['memory_store']
        with self.connect() as db:
            mid = self.save('user', '我喜欢这首歌', 'music_room', db)
            store.enqueue_room_turn(db, [mid], 'music_room', {})
            store.enqueue_room_turn(db, [mid], 'music_room', {})
            self.assertEqual(db.execute('SELECT count(*) FROM memory_jobs').fetchone()[0], 1)
            with self.assertRaises(ValidationError):
                store.enqueue_room_turn(db, [mid], 'movie_watch', {})

    def test_extraction_has_room_evidence_boundaries(self):
        from domains.memory.lmc import LmcMemoryMixin, evidence
        from domains.memory.base import ValidationError
        prompt = LmcMemoryMixin().perception_prompt({'segment_id': 'room'}, ([], None))
        self.assertIn('字幕、歌词、引用的台词', prompt)
        self.assertIn('不是用户原话', prompt)
        raw = {'experience_id': 'assistant', 'actor': 'libra', 'source_status': 'active',
               'source_type': 'chat_message', 'content': '你喜欢这首歌'}
        with self.assertRaises(ValidationError):
            evidence(None, [{'experience_id': 'assistant', 'evidence_quote': '你喜欢这首歌',
                             'text': '用户喜欢这首歌'}], {'assistant': raw}, 'user')
