from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json
import tempfile
import unittest

from life_prototype.clock import TestClock
from life_prototype.activity_engine import Prototype
from life_prototype.local_configuration import configurations
from life_prototype.cognition import Cognition
from life_prototype.douban import Douban, DoubanUnavailable, durations, add_candidate
from life_prototype.skill_movie import heartbeat
from life_prototype import movie_reviews


class ReviewModel:
    provider = 'isolated-test'
    kind = 'fixture'

    def __init__(self, consult=False):
        self.consult = consult
        self.calls = []

    def complete(self, stage, payload):
        self.calls.append((stage, payload))
        if self.consult and payload['phase'] == 'draft':
            return {'consult_short_reviews': True, 'title': '', 'review': '', 'memory_summary': ''}, {}
        return {'consult_short_reviews': False, 'title': '普通一天的价值',
                'review': '比起消除所有遗憾，我更在意人如何承担自己的选择。珍惜日常并不是逃避失去，而是认真面对眼前仍然能够做的事。',
                'memory_summary': '比起反复重来，更珍惜认真承担选择的普通一天。'}, {}


class DoubanReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.world, self.cog_config, *_ = configurations()
        self.world['initial']['place'] = 'home.f2.media'
        self.key = 'movie:about_time'
        self.world['movies'] = {self.key: {'id': self.key, 'title': '时空恋旅人', 'year': 2013,
            'place': 'home.f2.media', 'source': 'confirmed_movie_library', 'available': True,
            'viewing_mode': 'active_time_simulation', 'duration_seconds': 60,
            'edition': 'isolated-clock-fixture', 'duration_source': 'https://example.org/runtime'}}
        self.clock = TestClock('2026-09-27T20:00:00+08:00')
        self.p = Prototype('reviews', self.world, self.clock, root=self.root)
        self.model = ReviewModel()
        self.cog = Cognition(self.p, self.model, self.cog_config)
        self.cog.resource_root = self.root
        folder = self.root/'libra/movie_knowledge'
        folder.mkdir(parents=True)
        (folder/'knowledge_cards.json').write_text(json.dumps({'cards': [{'movie_id': 'about_time',
            'summary': '蒂姆能够重回过去，逐渐理解失去与普通生活的价值。', 'themes': ['时间','选择']}]}, ensure_ascii=False), encoding='utf8')

    def finish(self, ident='viewing'):
        self.p.command('start:'+ident, self.p.snapshot()['revision'], 'start', activity_id=ident,
                       kind='watching', target=self.key)
        self.clock.advance(60)
        heartbeat(self.cog)

    def test_runtime_variants_and_missing_runtime_are_explicit(self):
        self.assertEqual(durations('123')[0]['duration_seconds'], 7380)
        self.assertEqual([d['duration_seconds'] for d in durations('165分钟 / 125分钟(美国版)')], [9900,7500])
        self.assertEqual(durations('PT2H3M')[0]['duration_seconds'], 7380)
        self.assertEqual(durations('未知'), [])
        self.assertEqual(durations('共30集，每集45分钟'), [])

    def test_read_only_cache_and_parameter_validation(self):
        runner = Mock(return_value=[{'id':'123','title':'电影','url':'https://evil.invalid/'}])
        client = Douban(self.cog, runner)
        first = client.call('search', q='电影', count=3)
        self.assertEqual(client.call('search', q='电影', count=3), first)
        runner.assert_called_once()
        self.assertEqual(first[0]['url'], 'https://movie.douban.com/subject/123/')
        for operation, args in [('mark_movie',{}), ('detail',{'id':'123;cmd'}), ('search',{'q':'a','count':90})]:
            with self.assertRaises(ValueError): client.call(operation, **args)

    def test_remote_failure_is_cached_without_sensitive_details(self):
        runner = Mock(side_effect=DoubanUnavailable('cookie=do-not-store'))
        client = Douban(self.cog, runner)
        for _ in range(2):
            with self.assertRaises(DoubanUnavailable): client.call('detail', id='123')
        runner.assert_called_once()
        with self.p.store.connect() as db:
            raw = db.execute("SELECT body FROM life_evidence WHERE category='douban_cache'").fetchone()[0]
        self.assertNotIn('do-not-store', raw)

    def test_discovered_candidate_survives_library_sync_and_no_runtime_rejected(self):
        detail = {'id':'123','title':'新电影','year':'2020','url':'https://movie.douban.com/subject/123/',
                  'summary':'影片资料','genres':['剧情'],'duration_options':[{'duration_seconds':6000,'label':'100分钟'}]}
        with patch.object(Douban, 'call', return_value=detail):
            added = add_candidate(self.cog, '123', 0)
            self.assertTrue(added['added'])
            self.assertFalse(add_candidate(self.cog, '123', 0)['added'])
            with self.assertRaises(ValueError): add_candidate(self.cog, '123', 9)
        from life_prototype.resource_library import sync
        with patch.object(self.cog.agenda, 'read', return_value=None):
            sync(self.cog, self.root)
        self.assertTrue(self.p.config['movies'][added['movie_id']]['available'])
        self.assertEqual(self.p.config['movies'][added['movie_id']]['duration_seconds'], 6000)

    def test_each_completed_round_gets_one_local_review_and_summary_memory(self):
        self.finish()
        with patch.object(Douban, 'status', return_value={'installed':False}):
            self.assertTrue(movie_reviews.process_one(self.cog))
            self.assertFalse(movie_reviews.process_one(self.cog))
        self.assertEqual(len(self.model.calls), 1)
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM life_movie_reviews').fetchone()[0], 'done')
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='movie_review_written'").fetchone()[0], 1)
            memory = db.execute("SELECT description FROM life_memories WHERE kind='thought'").fetchone()[0]
        self.assertIn('认真承担选择', memory)
        exported = list((self.p.store.path.parent/'movie-reviews').glob('*.md'))
        self.assertEqual(len(exported), 1)
        self.assertIn('普通一天的价值', exported[0].read_text(encoding='utf8'))
        self.finish('rewatch')
        with patch.object(Douban, 'status', return_value={'installed':False}):
            self.assertTrue(movie_reviews.process_one(self.cog))
        self.assertEqual(len(list((self.p.store.path.parent/'movie-reviews').glob('*.md'))), 2)

    def test_model_can_request_short_comments_before_writing(self):
        self.model.consult = True
        self.finish()
        detail = {'id':'123','title':'时空恋旅人','year':'2013','summary':'主题是时间和日常生活。'}
        with patch.object(movie_reviews, '_detail', return_value=detail), \
             patch.object(Douban, 'status', return_value={'installed':True}), \
             patch.object(Douban, 'call', return_value=[{'author':'观众','content':'关于普通生活的感想。'}]) as remote:
            movie_reviews.process_one(self.cog)
        remote.assert_called_once_with('reviews', id='123', count=5)
        self.assertEqual([p['phase'] for _,p in self.model.calls], ['draft','final'])
        self.assertEqual(self.model.calls[-1][1]['short_reviews'][0]['author'], '观众')

    def test_incomplete_viewing_has_no_review_and_missing_sources_wait_without_llm(self):
        self.p.command('start', self.p.snapshot()['revision'], 'start', activity_id='partial',kind='watching',target=self.key)
        self.clock.advance(20)
        self.p.command('stop', self.p.snapshot()['revision'], 'interrupt',activity_id='partial',reason='pause')
        with self.p.store.connect() as db:
            movie_reviews.initialize(db)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM life_movie_reviews').fetchone()[0], 0)
        self.p.command('resume', self.p.snapshot()['revision'], 'resume', activity_id='partial')
        self.clock.advance(40)
        heartbeat(self.cog)
        with patch.object(movie_reviews, '_detail', return_value=None), patch.object(movie_reviews, '_local_card', return_value=None):
            movie_reviews.process_one(self.cog)
        self.assertEqual(self.model.calls, [])
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT status,attempts FROM life_movie_reviews').fetchone(), ('waiting_sources',0))


if __name__ == '__main__':
    unittest.main()
