from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from life_prototype import book_library as library


class BookLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'life.sqlite3'
        self.state = {'reading': {}, 'reading_progress': {}}
        self.config = {'books': {}}
        self.cog = SimpleNamespace(
            resource_root=self.root, store=SimpleNamespace(connect=self.connect, path=self.path),
            p=SimpleNamespace(config=self.config, snapshot=lambda: self.state),
            clock=SimpleNamespace(now=lambda: datetime(2026, 9, 30, tzinfo=timezone.utc)),
            persona={}, calls=SimpleNamespace(ask=Mock(return_value={'body': '这本书让我关注人在选择面前如何承担责任。我也想听听你的理解。'})))
        folder = self.root / 'libra/reading_knowledge'
        folder.mkdir(parents=True)
        (folder / 'catalog.json').write_text(json.dumps({'books': [
            {'book_id': 'known', 'title': '已读的书', 'author': '作者', 'reading_status': 'read'}]}), encoding='utf8')
        (folder / 'knowledge_cards.json').write_text(json.dumps({'cards': [
            {'book_id': 'known', 'summary': '一部关于选择的小说。'}]}), encoding='utf8')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, table, body):
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS ' + table + '(body TEXT)')
            db.execute('INSERT INTO ' + table + ' VALUES(?)', (json.dumps(body),))

    def test_reading_books_lead_completed_books_then_unstarted_books(self):
        self.config['books']['known'] = {'title': '已读的书', 'author': '作者', 'version': 'v1', 'total_chars': 100}
        self.config['books']['current'] = {'title': '正在读的书', 'author': '另一作者', 'version': 'v1', 'total_chars': 100}
        self.config['books']['finished'] = {'title': '读完的书', 'author': '第三作者', 'version': 'v1', 'total_chars': 100}
        self.state['reading']['current:v1'] = 35
        self.state['reading']['finished:v1'] = 100
        self.add('life_owned_books', {'title': '新书', 'authors': ['作者']})
        self.add('life_dynamic_drafts', {'kind': 'book_introduction', 'book': {'title': '新书', 'author': '作者'}, 'body': '已有的购书简介'})
        self.add('life_quotes', {'work': {'kind': 'reading', 'title': '已读的书', 'author': '作者'},
                               'source': {'text': '留下的一句原文'}, 'thought': '已有的想法'})
        self.add('life_quotes', {'work': {'kind': 'watching', 'title': '已读的书'},
                               'source': {'text': '电影台词'}, 'thought': '不混入书库'})
        ordered = library.public_view(self.cog)
        books = {b['title']: b for b in ordered}
        self.assertEqual(len(books), 4)
        self.assertEqual([b['title'] for b in ordered], ['正在读的书', '读完的书', '已读的书', '新书'])
        self.assertEqual(books['已读的书']['progress_percent'], 0)
        self.assertEqual(books['已读的书']['reading_status'], 'unread')
        self.assertEqual(books['已读的书']['quotes'][0]['thought'], '已有的想法')
        self.assertEqual(len(books['已读的书']['quotes']), 1)
        self.assertEqual(books['正在读的书']['progress_percent'], 35)
        self.assertEqual(books['正在读的书']['reading_status'], 'reading')
        self.assertEqual(books['读完的书']['reading_status'], 'read')
        self.assertEqual(books['新书']['reading_status'], 'unread')
        self.assertEqual(books['新书']['introduction'], '已有的购书简介')
        self.assertFalse(any(k.startswith('_') for k in books['新书']))
        self.cog.calls.ask.assert_not_called()

    def test_introduction_for_old_book_is_persisted_once(self):
        self.assertTrue(library.process_one(self.cog))
        self.assertFalse(library.process_one(self.cog))
        self.cog.calls.ask.assert_called_once()
        payload = self.cog.calls.ask.call_args.args[2]
        self.assertEqual(payload['reading_status'], 'unread')
        self.assertTrue(payload['knowledge']['summary'])
        self.assertTrue(library.public_view(self.cog)[0]['introduction'])
        with self.connect() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='life_dynamic_drafts'").fetchone())

    def test_failure_retries_later_without_blocking_books(self):
        self.cog.calls.ask.side_effect = RuntimeError('offline')
        self.assertTrue(library.process_one(self.cog))
        self.assertFalse(library.process_one(self.cog))
        books = library.public_view(self.cog)
        self.assertEqual(books[0]['introduction_status'], 'retry')
        self.assertEqual(books[0]['reading_status'], 'unread')

    def test_same_title_different_authors_remain_separate(self):
        self.config['books']['other'] = {'title': '已读的书', 'author': '同名书另一作者'}
        books = library.public_view(self.cog)
        self.assertEqual(len(books), 2)
        self.assertEqual(sorted(b['reading_status'] for b in books), ['unread', 'unread'])

    def test_purchase_introduction_does_not_get_rewritten(self):
        self.add('life_dynamic_drafts', {'kind': 'book_introduction',
                 'book': {'title': '已读的书', 'author': '作者'}, 'body': '已经写好的简介'})
        self.assertFalse(library.process_one(self.cog))
        self.cog.calls.ask.assert_not_called()

    def test_manual_book_persists_and_waits_for_reading_to_make_quotes(self):
        with patch.object(library, 'tick'):
            library.add(self.cog, ' 新书名 ', ' 新作者 ')
        rows = library.public_view(self.cog)
        manual = next(row for row in rows if row['title'] == '新书名')
        self.assertEqual(manual['reading_status'], 'unread')
        self.assertEqual(manual['quotes'], [])
        self.assertEqual(len(library.public_view(self.cog)), 2)
        with self.assertRaisesRegex(ValueError, '已经在书库'):
            with patch.object(library, 'tick'):
                library.add(self.cog, '新书名', '新作者')
        with self.connect() as db:
            count = db.execute('SELECT count(*) FROM life_manual_books').fetchone()[0]
        self.assertEqual(count, 1)

    def test_manual_book_gets_introduction_without_quote_job(self):
        with patch.object(library, 'tick'):
            library.add(self.cog, '新书名', '新作者')
        self.assertTrue(library.process_one(self.cog))
        self.assertTrue(library.process_one(self.cog))
        manual = next(row for row in library.public_view(self.cog) if row['title'] == '新书名')
        self.assertTrue(manual['introduction'])
        self.assertEqual(manual['quotes'], [])
        with self.connect() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='life_quote_jobs'").fetchone())

    def test_manual_book_enters_reading_source_queue(self):
        from life_prototype import weread_library
        with patch.object(library, 'tick'):
            library.add(self.cog, '新书名', '新作者')
        weread_library.bootstrap(self.cog)
        with self.connect() as db:
            row = db.execute("SELECT status,body FROM life_weread_library WHERE owned_id LIKE 'manual:%'").fetchone()
        self.assertEqual(row[0], 'pending')
        self.assertEqual(json.loads(row[1])['owned']['title'], '新书名')


if __name__ == '__main__':
    unittest.main()
