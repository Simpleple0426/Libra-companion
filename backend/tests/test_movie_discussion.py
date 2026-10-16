import json
import unittest
from unittest.mock import Mock
from application.movie_discussion import summarize
from application.movie_room_agent import MovieAgent


class MovieDiscussionTests(unittest.TestCase):
    def setUp(self):
        self.messages = [{'id': 1, 'role': 'user', 'content': '这次没有哭，下次想再看。', 'created_at': '2026-10-08T12:00:00+08:00'}]

    def test_grounded_summary_and_future_plan(self):
        def generate(prompt):
            self.assertIn('未来约定不能写成已完成', prompt)
            self.assertIn('测试电影', prompt)
            return json.dumps({'items': [{'text': '用户表示这次没有哭，并希望下次重看。',
                                         'evidence': [{'message_id': 1, 'quote': '这次没有哭，下次想再看。'}]}]})
        self.assertEqual(len(summarize({'title': '测试电影'}, self.messages, generate)), 1)

    def test_unobserved_message_and_fabricated_quote_rejected(self):
        for ident, quote in [(2, '这次没有哭'), (1, '很开心')]:
            with self.subTest(ident=ident), self.assertRaises(ValueError):
                summarize({'title': '测试电影'}, self.messages, lambda _: json.dumps({
                    'items': [{'text': '用户很开心', 'evidence': [{'message_id': ident, 'quote': quote}]}]}))

    def test_empty_discussion(self):
        self.assertEqual(summarize({'title': '测试电影'}, [], lambda _: '{"items":[]}'), [])

    def test_background_uses_fresh_session_and_persists_linked_dialogue(self):
        records = Mock()
        records.discussion_messages.return_value = self.messages
        records.get.return_value = {'title': '测试电影'}
        response = Mock(text=json.dumps({'items': [{'text': '用户希望重看',
                        'evidence': [{'message_id': 1, 'quote': '下次想再看'}]}]}), session_id='summary-session')
        runtime = {'run_cli': Mock(return_value=response), 'CHAT_MODEL': 'test-model', '_record_llm_usage': Mock()}
        MovieAgent(runtime, records, Mock())._discussion('view-1')
        self.assertIsNone(runtime['run_cli'].call_args.kwargs['session_id'])
        self.assertEqual(records.discussion_result.call_args.args[0], 'view-1')
        self.assertEqual(records.discussion_result.call_args.args[2], self.messages)

    def test_background_failure_records_error(self):
        records = Mock()
        records.discussion_messages.return_value = self.messages
        records.get.return_value = {'title': '测试电影'}
        runtime = {'run_cli': Mock(side_effect=RuntimeError('unavailable')), 'CHAT_MODEL': 'test-model'}
        with self.assertLogs('application.movie_room_agent', level='ERROR'):
            MovieAgent(runtime, records, Mock())._discussion('view-1')
        records.discussion_result.assert_called_once_with('view-1')

    def test_no_user_dialogue_does_not_call_model(self):
        records = Mock()
        records.discussion_messages.return_value = []
        runtime = {'run_cli': Mock()}
        MovieAgent(runtime, records, Mock())._discussion('view-1')
        runtime['run_cli'].assert_not_called()
        records.discussion_result.assert_called_once_with('view-1', [])
