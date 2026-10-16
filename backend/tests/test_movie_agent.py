from contextvars import ContextVar
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from application.movie_room_agent import MovieAgent


class Replies(list):
    def __init__(self):
        super().__init__(['电影室的回复'])
        self.payload = {'memory_experience': {'invented': True}}
        self.context = {'turn_id': 'turn'}


class MovieAgentTests(unittest.TestCase):
    def setUp(self):
        self.records = Mock()
        self.records.chat_receipt.return_value = None
        self.records.accept_chat.return_value = {'replies': None}
        self.records.get.return_value = {'summary': '实际观察', 'quotes': []}
        self.records.messages.return_value = []
        self.watch = Mock()
        self.watch.current.return_value = {'id': 'current'}
        self.replies = Replies()
        self.runtime = {'_require_awake': Mock(), 'save_message': Mock(),
            'active_cognitive_turn': ContextVar('movie-test', default=None),
            '_prepare_generation_turn': Mock(return_value={'turn_id': 'turn'}),
            'turn_pipeline': Mock(), '_run_codex': Mock(return_value=(self.replies, 'existing-thread')),
            '_save_assistant_outputs': Mock(return_value=[{'id': 123}])}
        self.runtime['turn_pipeline'].committed_messages.return_value = None
        self.agent = MovieAgent(self.runtime, self.records, self.watch)

    def test_chat_uses_existing_agent_and_movie_source(self):
        self.agent.chat(SimpleNamespace(viewing_id=None, request_id='req', message='这个镜头'))
        self.runtime['_run_codex'].assert_called_once()
        self.assertEqual(self.runtime['_run_codex'].call_args.kwargs, {'source': 'movie_chat'})
        self.assertNotIn('memory_experience', self.replies.payload)
        self.records.finish_chat.assert_called_once_with('req', 'current', [{'id': 123}])
        self.assertIsNone(self.runtime['active_cognitive_turn'].get())

    def test_retry_after_switching_movie_uses_original_receipt(self):
        self.records.chat_receipt.return_value = {'viewing_id': 'original'}
        self.records.accept_chat.return_value = {'replies': '[{"id":123}]'}
        result = self.agent.chat(SimpleNamespace(viewing_id=None, request_id='req', message='原消息'))
        self.assertEqual(self.records.accept_chat.call_args.args[2], 'original')
        self.runtime['_run_codex'].assert_not_called()
        self.assertEqual(result['messages'], [{'id': 123}])

    def test_review_commits_artifact_not_chat(self):
        pipeline = self.runtime['turn_pipeline']
        pipeline.prepare_delivery.return_value = (self.replies, {'accepted': True})
        self.agent._review('movie')
        self.assertEqual(self.runtime['_run_codex'].call_args.kwargs, {'source': 'movie_review'})
        pipeline.commit_artifact.assert_called_once()
        self.runtime['_save_assistant_outputs'].assert_not_called()
        connection = Mock()
        pipeline.commit_artifact.call_args.args[3](connection)
        self.assertEqual(connection.execute.call_args.args[1], ('电影室的回复', 'movie'))

    def test_missing_evidence_never_calls_model_for_review(self):
        self.records.get.return_value = {'summary': '', 'quotes': []}
        self.agent._review('movie')
        self.runtime['_run_codex'].assert_not_called()
        self.records.review_result.assert_called_once_with('movie')
