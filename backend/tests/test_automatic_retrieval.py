import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from application.automatic_retrieval import preload, contextual_plan
from application.chat_research import research
from application.knowledge_retriever import KnowledgeRetriever


class AutomaticRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.history = '<canonical_shared_history>' + json.dumps({'reviewed_scenes': [
            {'history_id': 'h1', 'excerpt_ids': ['excerpt1']}], 'source_excerpts': []}) + '</canonical_shared_history>'
        self.situation_model = Mock(side_effect=lambda prompt: {'situations': [{
            'subject': 'user', 'description': '用户谈起与左然的共同经历',
            'evidence': [{'source_id': 'current', 'quote': json.loads(prompt.split('\n')[-1])['sources'][0]['text']}]}]})
        self.retriever = KnowledgeRetriever(
            memory_store=SimpleNamespace(recall=Mock(return_value={'memories': [{'memory_id': 'm1', 'content': '往事'}]})),
            character_store=SimpleNamespace(search=Mock(return_value=[{'id': 'c1'}])),
            shared_history_store=SimpleNamespace(context_for=Mock(return_value=self.history)),
            evidence_formatter=Mock(return_value='角色参考'), situation_model=self.situation_model)
        self.retriever.personal_memory = Mock(return_value={'memories': [{'memory_id': 'm1', 'content': '往事'}]})
        self.context = {'memory_context': {'memories': []}, 'character_evidence': [],
                        'degraded_components': [], 'current_event': {'content': '上次一起看电影'},
                        'memory_usage': {}}

    def test_substantive_chat_preloads_all_three_with_trace(self):
        preload(self.retriever, self.context, '上次一起看电影', [], 'session')
        self.assertEqual(self.context['memory_context']['memories'][0]['memory_id'], 'm1')
        self.assertIn(self.history, self.context['supporting_knowledge'])
        for store in ('personal', 'character', 'shared_history'):
            self.assertEqual(self.context['automatic_retrieval']['stores'][store]['injected_count'], 1)

    def test_greeting_skips_queries(self):
        preload(self.retriever, self.context, '早上好！', [], 'session')
        self.retriever.personal_memory.assert_not_called()
        self.retriever.character_store.search.assert_not_called()
        self.situation_model.assert_not_called()

    def test_chat_searches_summarized_situation_before_character_recall(self):
        order = []
        self.situation_model.side_effect = lambda prompt: order.append('summary') or {'situations': [{
            'subject': 'user', 'description': '用户分享今天做饭的经历',
            'evidence': [{'source_id': 'current', 'quote': '今天做饭了'}]}]}
        self.retriever.character_store.search.side_effect = lambda text, **kwargs: order.append(text) or [{'id': 'c1'}]
        preload(self.retriever, self.context, '今天做饭了', [], 'session')
        self.assertEqual(order, ['summary', '用户分享今天做饭的经历'])
        self.assertEqual(self.context['character_situations'][0]['text'], '用户分享今天做饭的经历')

    def test_missing_or_failed_summary_does_not_search_raw_message(self):
        for response in ({'situations': []}, RuntimeError('unavailable')):
            with self.subTest(response=response):
                self.retriever.character_store.search.reset_mock()
                self.situation_model.side_effect = response if isinstance(response, Exception) else None
                self.situation_model.return_value = response
                preload(self.retriever, self.context, '今天做饭了', [], 'session')
                self.retriever.character_store.search.assert_not_called()
                self.assertEqual(self.context['character_evidence'], [])

    def test_situation_model_receives_latest_ten_history_messages(self):
        recent = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': f'历史消息{i}'}
                  for i in range(12)]
        preload(self.retriever, self.context, '今天做饭了', recent, 'session')
        prompt = self.situation_model.call_args.args[0]
        sources = json.loads(prompt.split('\n')[-1])['sources']
        self.assertEqual(sources[0]['text'], '今天做饭了')
        self.assertEqual([source['text'] for source in sources[1:]],
                         [f'历史消息{i}' for i in range(2, 12)])

    def test_failure_in_one_library_does_not_drop_other_evidence(self):
        self.retriever.personal_memory.side_effect = RuntimeError('unavailable')
        preload(self.retriever, self.context, '上次一起看电影', [], 'session')
        self.assertEqual(self.context['automatic_retrieval']['stores']['personal']['status'], 'failed')
        self.assertEqual(self.context['character_evidence'], [{'id': 'c1'}])
        self.assertIn(self.history, self.context['supporting_knowledge'])

    def test_personal_and_character_preload_run_concurrently(self):
        personal_started = threading.Event()
        character_started = threading.Event()

        def personal(*args, **kwargs):
            personal_started.set()
            self.assertTrue(character_started.wait(1))
            return {'memories': []}

        def character(*args, **kwargs):
            character_started.set()
            self.assertTrue(personal_started.wait(1))
            return SimpleNamespace(character_evidence=[], character_situations=[],
                                   degraded_components=[])

        self.retriever.personal_memory.side_effect = personal
        self.retriever.supporting_knowledge = Mock(side_effect=character)
        started = time.perf_counter()
        preload(self.retriever, self.context, '今天工作让我很累', [], 'session')
        self.assertLess(time.perf_counter() - started, 1)

    def test_nonhistorical_input_does_not_query_canonical_history(self):
        preload(self.retriever, self.context, '今天工作让我很累', [], 'session')
        self.retriever.shared_history_store.context_for.assert_not_called()
        self.retriever.personal_memory.assert_called_once()

    def test_proactive_plan_adds_verbatim_user_topics_not_assistant_claims(self):
        result = contextual_plan('定时检查', [{'role': 'assistant', 'content': '未经证实的说法'},
                                               {'role': 'user', 'content': '上次一起看电影'}], proactive=True)
        self.assertIn({'text': '上次一起看电影', 'kind': 'context'}, result)
        self.assertFalse(any('未经证实' in p['text'] for p in result))

    def test_tool_loop_preserves_preloaded_evidence_without_queries(self):
        preload(self.retriever, self.context, '上次一起看电影', [], 'session')
        decision = SimpleNamespace(executor=SimpleNamespace(bind_retriever=Mock(), receipts=[]), services={}, receipts={})
        research(self.context, decision, self.retriever, lambda _: {'messages': ['回应']}, [], 'session', main_thread=True)
        self.assertIn(self.history, self.context['supporting_knowledge'])
        self.assertEqual(self.context['memory_usage']['allowed_memory_ids'], ['m1'])


if __name__ == '__main__':
    unittest.main()
