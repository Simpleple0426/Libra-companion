import unittest
from unittest.mock import patch
from application.movie_douban_background import fetch


class DoubanBackgroundTests(unittest.TestCase):
    @patch('application.movie_douban_background.execute')
    def test_title_year_and_bounded_comments(self, call):
        call.side_effect = [
            [{'id': '123', 'title': '测试电影 (2026)'}],
            {'id': '123', 'title': '测试电影', 'year': '2026', 'summary': '简介'},
            [{'author': '观众', 'content': '观后感'}],
        ]
        result = fetch('测试电影（2026）')
        self.assertEqual(result['identity']['id'], '123')
        self.assertEqual(result['reviews'][0]['content'], '观后感')
        self.assertEqual([c.args[0] for c in call.call_args_list], ['movies.search', 'movies.detail', 'movies.reviews'])

    @patch('application.movie_douban_background.execute')
    def test_multiple_editions_need_year(self, call):
        call.return_value = [{'id': '1', 'title': '测试电影 (2020)'}, {'id': '2', 'title': '测试电影 (2026)'}]
        self.assertEqual(fetch('测试电影')['status'], 'ambiguous')
        call.assert_called_once()

    @patch('application.movie_douban_background.execute')
    def test_detail_mismatch_rejected(self, call):
        call.side_effect = [[{'id': '1', 'title': '测试电影'}], {'id': '2', 'title': '另一部电影'}]
        with self.assertRaisesRegex(ValueError, 'identity_mismatch'):
            fetch('测试电影')
