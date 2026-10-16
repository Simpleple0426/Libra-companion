import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import tempfile
import threading
import unittest

from life_prototype import quote_notebook as notes
from life_prototype.quote_sources import allowed, normalize, author_name, douban_quotes, wiki_quotes, Sources
from life_prototype.clock import TestClock
from life_prototype.activity_engine import Prototype
from life_prototype.local_configuration import configurations
from life_prototype.cognition import Cognition
from life_prototype.skill_movie import heartbeat


class QuoteModel:
    provider = 'isolated-test'
    kind = 'fixture'

    def complete(self, stage, payload):
        assert stage == 'quote_note'
        return {'entries':[{'candidate_id':payload['candidates'][0]['id'], 'translation':'',
                            'thought':'这句话让我想到认真倾听的重要。如果有机会，我想与你一起讨论，也想知道你对这个选择有什么不同的看法。'}]}, {}


class QuoteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        world, config, *_ = configurations()
        world['initial']['place'] = 'home.f2.media'
        self.key = 'movie:fixture'
        world['movies'] = {self.key:{'id':self.key,'title':'测试电影','original_title':'Fixture Film',
            'year':2020,'place':'home.f2.media','source':'confirmed_movie_library','available':True,
            'viewing_mode':'active_time_simulation','duration_seconds':3600,'edition':'fixture',
            'duration_source':'https://example.org'}}
        self.clock = TestClock('2026-09-27T20:00:00+08:00')
        self.p = Prototype('quotes',world,self.clock,root=self.root)
        self.cog = Cognition(self.p,QuoteModel(),config)
        self.cog.resource_root = self.root
        self.source = {'text':'这是一句用于测试的虚构短句。','url':'https://zh.wikiquote.org/wiki/Fixture',
                       'language':'zh','location':'后半部','position_verified':False}

    def start(self):
        self.p.command('start',self.p.snapshot()['revision'],'start',activity_id='view',kind='watching',target=self.key)

    def due(self):
        self.start()
        for _ in range(5):
            self.clock.advance(60); heartbeat(self.cog)
        return notes.enqueue(self.cog)

    def test_source_allowlist_and_author_cleanup(self):
        self.assertTrue(allowed('https://en.wikiquote.org/wiki/Test'))
        for url in ('http://en.wikiquote.org/wiki/Test','https://en.wikiquote.org.evil/x',
                    'https://user@en.wikiquote.org/x','https://book.douban.com:8000/x','https://example.org'):
            self.assertFalse(allowed(url))
        self.assertEqual(author_name('（英）阿加莎·克里斯蒂著；夏阳译'),'阿加莎克里斯蒂')
        self.assertEqual(normalize('“Hello, WORLD!”'),normalize('hello world'))

    def test_parsers_exclude_comments_references_and_unsourced_sections(self):
        html = '<div class="blockquote-list"><ul><li><figure>这是作品里的测试短句。<a>查看原文</a></figure><div class="comment">网友自己的想法</div><figcaption>第九章</figcaption></li></ul></div>'
        rows = douban_quotes(html,'https://book.douban.com/subject/1/blockquotes',{})
        self.assertEqual(rows[0]['text'],'这是作品里的测试短句。')
        self.assertEqual(rows[0]['location'],'第九章')
        wiki = '<div class="mw-parser-output"><h2>Character</h2><ul><li>A short fictional quote.<ul><li>A source note</li></ul></li></ul><h2>Unsourced</h2><ul><li>Not a verified quote</li></ul><h2>External links</h2><ul><li>External link text</li></ul></div>'
        self.assertEqual([r['text'] for r in wiki_quotes(wiki,'https://en.wikiquote.org/wiki/Test','en','Test')],['A short fictional quote.'])

    def test_five_active_minutes_and_one_batch_per_work_per_day(self):
        self.start()
        self.assertIsNone(notes.enqueue(self.cog))
        # Offline time does not satisfy the active viewing threshold.
        self.clock.advance(1000); heartbeat(self.cog)
        self.assertIsNone(notes.enqueue(self.cog))
        for _ in range(5): self.clock.advance(60); heartbeat(self.cog)
        ident = notes.enqueue(self.cog)
        self.assertTrue(ident)
        notes.process(self.cog,ident,SimpleNamespace(collect=lambda work:[]))
        self.assertIsNone(notes.enqueue(self.cog))

    def test_original_saved_once_across_sessions_punctuation_and_restart(self):
        ident = self.due()
        notes.process(self.cog,ident,SimpleNamespace(collect=lambda work:[self.source]))
        with self.p.store.connect() as db:
            body = json.loads(db.execute('SELECT body FROM life_quote_jobs WHERE id=?',(ident,)).fetchone()[0])
            body.pop('payload')
            db.execute("INSERT INTO life_quote_jobs VALUES('next','pending',?)",(json.dumps(body),))
        duplicate = {**self.source,'text':'这是一句 用于测试的虚构短句！'}
        with patch.object(self.cog.calls,'ask',side_effect=AssertionError('duplicate invoked model')):
            notes.process(self.cog,'next',SimpleNamespace(collect=lambda work:[duplicate]))
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM life_quotes').fetchone()[0],1)
            record = json.loads(db.execute('SELECT body FROM life_quotes').fetchone()[0])
            self.assertEqual(record['source']['location'],'后半部')
            self.assertFalse(record['position_verified'])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM life_memories WHERE id LIKE 'mem:quote:%'").fetchone()[0],1)
        files = list((self.p.store.path.parent/'quote-notebook').glob('*.md'))
        self.assertEqual(len(files),1)
        self.assertIn('左然的想法',files[0].read_text(encoding='utf8'))
        files[0].unlink(); notes.export(self.cog)
        self.assertTrue(files[0].exists())

    def test_unknown_candidate_fails_without_fabricated_quote(self):
        ident = self.due()
        with patch.object(self.cog.calls,'ask',return_value={'entries':[{'candidate_id':'invented','translation':'','thought':'想法'*30}]}):
            notes.process(self.cog,ident,SimpleNamespace(collect=lambda work:[self.source]))
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM life_quotes').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT status FROM life_quote_jobs WHERE id=?',(ident,)).fetchone()[0],'failed')

    def test_empty_sources_skip_model(self):
        ident = self.due()
        with patch.object(self.cog.calls,'ask',side_effect=AssertionError('unnecessary model')):
            notes.process(self.cog,ident,SimpleNamespace(collect=lambda work:[]))
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM life_quote_jobs WHERE id=?',(ident,)).fetchone()[0],'skipped')

    def test_slow_lookup_runs_off_scheduler_and_does_not_duplicate_workers(self):
        self.due()
        started, release = threading.Event(), threading.Event()
        def slow(*args): started.set(); release.wait(3)
        with patch.object(notes,'process',side_effect=slow) as process:
            notes.tick(self.cog)
            self.assertTrue(started.wait(1))
            notes.tick(self.cog)
            process.assert_called_once()
            self.clock.advance(30); heartbeat(self.cog)
            self.assertEqual(self.p.snapshot()['activities']['view']['progress'],330)
            release.set()
            notes._workers[str(self.cog.store.path.resolve())].join(2)

    def test_source_order_does_not_expand_after_failures(self):
        sources = Sources()
        with patch.object(sources,'book',side_effect=OSError('unavailable')) as book, \
             patch.object(sources,'wiki',return_value=[]) as wiki:
            self.assertEqual(sources.collect({'kind':'reading','title':'测试'}),[])
            book.assert_called_once()
            self.assertEqual([call.args[1] for call in wiki.call_args_list],['zh','en'])

    def test_reading_uses_active_time_without_opening_book_content(self):
        state = self.p.snapshot()
        state['active'] = 'read'
        state['activities']['read'] = {'id':'read','kind':'reading','target':'book:test','status':'running',
            'reading_mode':'structure_simulation','simulated_seconds':300,'progress':2000}
        self.p.config['books']['book:test'] = {'title':'测试书','author':'测试作者','manifest_path':'must-not-read'}
        with patch.object(self.p,'snapshot',return_value=state):
            ident = notes.enqueue(self.cog)
        notes.process(self.cog,ident,SimpleNamespace(collect=lambda work:[self.source]))
        with self.p.store.connect() as db:
            record = json.loads(db.execute('SELECT body FROM life_quotes').fetchone()[0])
        self.assertEqual(record['work']['kind'],'reading')
        self.assertEqual(record['progress_at_request'],2000)

    def test_english_original_preserved_and_translation_labelled(self):
        ident = self.due()
        source = {**self.source,'text':'A fictional sentence for this isolated test.','language':'en',
                  'url':'https://en.wikiquote.org/wiki/Fixture'}
        def answer(call_id,stage,payload):
            return {'entries':[{'candidate_id':payload['candidates'][0]['id'],'translation':'这是一句测试译文。',
                                'thought':'这句话让我想到认真倾听的重要。如果有机会，我想与你一起讨论，也想知道你对这个选择有什么不同的看法。'}]}
        with patch.object(self.cog.calls,'ask',side_effect=answer):
            notes.process(self.cog,ident,SimpleNamespace(collect=lambda work:[source]))
        text = next((self.p.store.path.parent/'quote-notebook').glob('*.md')).read_text(encoding='utf8')
        self.assertIn(source['text'],text)
        self.assertIn('译文（左然自译）：这是一句测试译文。',text)


if __name__ == '__main__': unittest.main()
