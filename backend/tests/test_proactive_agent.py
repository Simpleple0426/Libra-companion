from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from application.proactive_agent import prepare, prompt, finish, batch
from application.main_chat_agent import run


class ProactiveAgentTests(unittest.TestCase):
    def test_batch_only_combines_already_pending_adjacent_events(self):
        events = [{'id': 'a', 'occurred_at': '2026-10-12T00:00:00+00:00'},
                  {'id': 'b', 'occurred_at': '2026-10-12T00:00:30+00:00'},
                  {'id': 'c', 'occurred_at': '2026-10-12T00:04:00+00:00'}]
        self.assertEqual([item['id'] for item in batch(events)], ['a', 'b'])

    def context(self):
        return {'response_plan': {}, 'current_event': {'content': '工作开始'},
                'memory_context': {'memories': []}, 'memory_usage': {},
                'degraded_components': [],
                'decision_recent_messages': [{'role': 'user', 'content': '继续刚才的话题'}]}

    def test_primary_thread_can_choose_silence_without_retry(self):
        context = self.context()
        prepare(context)
        decision = SimpleNamespace(executor=SimpleNamespace(bind_retriever=Mock(), receipts=[]), receipts={}, services={})
        generate = Mock(return_value=SimpleNamespace(text='{"messages":[]}', session_id='same'))
        result = run(prompt(context), 'same', context, decision, Mock(), [], generate, Mock(), Mock())
        self.assertEqual(result.text, '{"messages":[]}')
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(context['chat_research']['stop_reason'], 'replied')
        finish(context, [])
        self.assertFalse(context['response_plan']['should_send'])

    def test_prompt_keeps_dialogue_and_does_not_preselect_reporting(self):
        context = self.context()
        prepare(context)
        text = prompt(context)
        self.assertIn('继续刚才的话题', text)
        self.assertNotIn('已决定主动发送', text)
        finish(context, ['自然回应'])
        self.assertTrue(context['response_plan']['should_send'])

    def test_prompt_exposes_initiative_and_checkin_context(self):
        context = self.context()
        context['initiative_policy'] = {
            'scheduled_silence_streak': 2,
            'seconds_since_last_proactive_message': 1800,
            'persistent_silence_contact': True,
        }
        context['checkin_state'] = {'needs': {'connection': {'value': 0.8}}}
        prepare(context)
        text = prompt(context)
        self.assertIn('initiative_policy', text)
        self.assertIn('checkin_state', text)
        self.assertIn('超过三十分钟没有主动联系', text)
        self.assertIn('不要把联系写成定时打卡', text)

    def test_persistent_prompt_uses_lmc_only_as_fallback_topic(self):
        context = self.context()
        context['initiative_policy'] = {'persistent_silence_contact': True}
        context['memory_context'] = {'memories': [{
            'memory_id': 'mem-1', 'memory_kind': 'lmc',
            'memory_subtype': 'relationship_moment', 'primary_scope': 'shared',
            'title': '一起看电影', 'content': '她提过想一起看一部电影',
            'occurred_at': '2026-10-01T12:00:00+08:00', 'confidence': 0.9,
            'usage_hint': '过去的记忆，不证明现在仍在进行',
        }, {
            'memory_id': 'reflection-1', 'memory_kind': 'reflection',
            'content': '不应作为真实记忆话题',
        }]}
        prepare(context)
        text = prompt(context)
        self.assertIn('recollection_candidates', text)
        self.assertIn('mem-1', text)
        self.assertNotIn('reflection-1', text)
        self.assertIn('前三者都没有自然话题时', text)
        self.assertIn('memory_used_ids', text)

    def test_persistent_silence_rejects_empty_and_retries_nonempty(self):
        context = self.context()
        context['initiative_policy'] = {'persistent_silence_contact': True}
        prepare(context)
        decision = SimpleNamespace(executor=SimpleNamespace(bind_retriever=Mock(), receipts=[]), receipts={}, services={})
        generate = Mock(side_effect=[
            SimpleNamespace(text='{"messages":[]}', session_id='same'),
            SimpleNamespace(text='{"messages":["想起你了，刚才的事还顺利吗？"]}', session_id='same'),
        ])
        result = run(prompt(context), 'same', context, decision, Mock(), [], generate, Mock(), Mock())
        self.assertEqual(result.text, '{"messages":["想起你了，刚才的事还顺利吗？"]}')
        self.assertEqual(generate.call_count, 2)
