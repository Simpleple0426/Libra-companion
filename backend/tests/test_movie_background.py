import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from application.movie_background import MovieBackground
from application.watch_together import WatchService
from infrastructure.models.cli import _parse_codex


class MovieBackgroundTests(unittest.TestCase):
    def setUp(self):
        self.lookup = patch('application.movie_douban_background.fetch', side_effect=RuntimeError('offline')).start()
        self.addCleanup(patch.stopall)

    def service(self, searched=True):
        result = SimpleNamespace(searched_web=searched, session_id='research', text=json.dumps({
            'status': 'ready', 'identity': '电影 / 2020 / 导演', 'brief': '背景与主题',
            'sources': [{'kind': 'intro', 'title': '介绍', 'url': 'https://example.com/intro'},
                        {'kind': 'review', 'title': '影评', 'url': 'https://example.com/review'}]}))
        r = {'run_cli': Mock(return_value=result), 'CHAT_MODEL': 'test',
             '_record_llm_usage': Mock(), '_parse_json_object': json.loads}
        service = MovieBackground(r, None)
        service.jobs['one'] = {'status': 'loading'}
        return service, r

    def test_research_is_separate_and_requires_real_search(self):
        service, r = self.service()
        service._research('one', '电影')
        self.assertEqual(service.get('one')['status'], 'ready')
        self.assertIsNone(r['run_cli'].call_args.kwargs['session_id'])
        self.assertTrue(r['run_cli'].call_args.kwargs['web_search'])
        service, _ = self.service(False)
        service._research('one', '电影')
        self.assertEqual(service.get('one')['status'], 'unavailable')

    def test_missing_title_and_stale_job(self):
        service, r = self.service()
        service.start({'id': 'new', 'title': ''})
        r['run_cli'].assert_not_called()
        self.assertEqual(service.get('new')['status'], 'missing_title')
        service._research('one', '旧电影')
        self.assertEqual(service.get('new')['status'], 'missing_title')
        self.assertEqual(service.get('one')['status'], 'unavailable')

    def test_search_evidence_from_cli_events(self):
        result = _parse_codex(json.dumps({'type':'item.completed','item':{'type':'web_search'}}), None)
        self.assertTrue(result.searched_web)
        self.assertFalse(_parse_codex('', None).searched_web)

    def test_douban_preferred_without_web_and_sources_preserved(self):
        self.lookup.side_effect = None
        self.lookup.return_value = {'status': 'ready', 'introduction': '介绍', 'reviews': ['评论'],
            'sources': [{'kind': 'intro', 'title': '简介', 'url': 'https://movie.douban.com/subject/1/'},
                        {'kind': 'review', 'title': '影评', 'url': 'https://movie.douban.com/subject/1/reviews/'}]}
        service, r = self.service(False)
        service._research('one', '电影')
        self.assertFalse(r['run_cli'].call_args.kwargs['web_search'])
        self.assertEqual(service.get('one')['provider'], 'douban')
        self.assertEqual(service.get('one')['sources'], self.lookup.return_value['sources'])

    def test_ambiguous_douban_does_not_guess(self):
        self.lookup.side_effect = None
        self.lookup.return_value = {'status': 'ambiguous'}
        service, r = self.service()
        service._research('one', '同名电影')
        r['run_cli'].assert_not_called()
        self.assertEqual(service.get('one')['status'], 'ambiguous')

    def test_first_observation_waits_and_injects_once(self):
        background = Mock()
        background.get.return_value = {'status': 'loading'}
        generate = Mock(return_value=([], 'summary'))
        clock = [0]
        watch = WatchService(generate, lambda _: [], clock=lambda: clock[0], background=background)
        watch.decode = lambda _: b'frame'
        ident = watch.start('电影', 'normal')['session_id']
        self.assertEqual(watch.observe(ident, 0, '')['status'], 'preparing')
        generate.assert_not_called()
        background.get.return_value = {'status': 'ready', 'brief': '背景'}
        watch.observe(ident, 1, '')
        self.assertEqual(generate.call_args.args[0]['movie_background']['brief'], '背景')
        clock[0] = 130
        watch.control(ident, 'heartbeat')
        watch.observe(ident, 2, '')
        self.assertNotIn('movie_background', generate.call_args.args[0])
