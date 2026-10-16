import unittest
from application.contact_decision import decide
from application.proactive_topic import writing_context


class ProactiveTopicTests(unittest.TestCase):
    def context(self):
        return {'response_plan': {}, 'delivery_policy': {'can_send': True},
                'unified_event': {'source': 'libra_life_state', 'description': '开始看电影'},
                'memory_context': {'memories': [{'memory_id': 'm1', 'content': '上次一起看电影'}]},
                'decision_recent_messages': [{'role': 'assistant', 'content': '名字已经定下来'}]}

    def test_selected_memory_reaches_writer(self):
        c = self.context()
        topic = {'kind': 'memory', 'angle': '从今天观影联想到以前的讨论', 'novelty': '结合新的观影情境', 'memory_ids': ['m1']}
        decide(c, lambda *_: {'should_send': True, 'reason': '自然关联',
                             'life_share_basis': 'conversation_connection', 'topic': topic})
        self.assertTrue(c['response_plan']['should_send'])
        self.assertIn('m1', writing_context(c))

    def test_unknown_memory_blocks_contact(self):
        c = self.context()
        decide(c, lambda *_: {'should_send': True, 'reason': '回忆', 'life_share_basis': 'conversation_connection', 'topic': {
            'kind': 'memory', 'angle': '回忆', 'novelty': '新关联', 'memory_ids': ['invented']}})
        self.assertFalse(c['response_plan']['should_send'])

    def test_settled_topic_can_remain_silent(self):
        c = self.context()
        def model(stage, prompt):
            self.assertIn('已确认、已解决、已收尾', prompt)
            return {'should_send': False, 'reason': '名字已定，没有新内容', 'topic': None}
        decide(c, model)
        self.assertFalse(c['response_plan']['should_send'])

    def test_actual_new_event_requires_observed_quote(self):
        c = self.context()
        decide(c, lambda *_: {'should_send': True, 'reason': '分享', 'life_share_basis': 'specific_content', 'topic': {
            'kind': 'event', 'angle': '分享观影', 'novelty': '当前新活动', 'evidence_quotes': ['已经看完']}})
        self.assertFalse(c['response_plan']['should_send'])

    def test_checkin_without_eligible_memory_does_not_generate_topic(self):
        c = self.context()
        c['checkin_recollection'] = True
        c['memory_context']['memories'] = []
        def model(*_):
            self.fail('no candidate must not invoke model')
        decide(c, model)
        self.assertEqual(c['response_plan']['reason'], 'no_eligible_recollection')

    def test_routine_life_contact_without_share_basis_is_allowed(self):
        c = self.context()
        decide(c, lambda *_: {'should_send': True, 'reason': '换了活动想她了', 'topic': {
            'kind': 'event', 'angle': '我开始看电影了', 'novelty': '开始新活动',
            'evidence_quotes': ['开始看电影']}})
        self.assertTrue(c['response_plan']['should_send'])
        self.assertEqual(c['contact_decision_status'], 'completed')

    def test_life_silence_is_not_overridden_by_persistent_silence(self):
        c = self.context()
        c['initiative_policy'] = {'persistent_silence_contact': True}
        def model(stage, prompt):
            self.assertIn('自主判断是否联系', prompt)
            self.assertIn('上班、离开家、到达家', prompt)
            return {'should_send': False, 'reason': '只是切换活动，没有分享内容'}
        decide(c, model)
        self.assertFalse(c['response_plan']['should_send'])

    def test_other_contact_sources_do_not_require_life_share_basis(self):
        c = self.context()
        c['unified_event']['source'] = 'user_life_activity'
        decide(c, lambda *_: {'should_send': True, 'reason': '新的具体交流', 'topic': {
            'kind': 'new', 'angle': '交流', 'novelty': '新的交流内容'}})
        self.assertTrue(c['response_plan']['should_send'])

    def test_committed_life_continuity_event_can_ground_contact(self):
        c = self.context()
        c['context_snapshot'] = {'local_life': {'life_continuity': {
            'recent_events': [{'description': 'Finished the book'}]}}}
        decide(c, lambda *_: {'should_send': True, 'reason': 'Follow up', 'topic': {
            'kind': 'event', 'angle': 'Book', 'novelty': 'Finished', 'evidence_quotes': ['Finished the book']}})
        self.assertTrue(c['response_plan']['should_send'])

    def test_saved_thought_can_ground_new_exchange_but_not_claimed_event(self):
        for kind, expected in [('new', True), ('event', False)]:
            with self.subTest(kind=kind):
                c = self.context()
                c['context_snapshot'] = {'local_life': {'life_continuity': {
                    'private_thoughts': [{'body': 'Would like to revisit this film'}]}}}
                decide(c, lambda *_: {'should_send': True, 'reason': 'Thought', 'topic': {
                    'kind': kind, 'angle': 'Film', 'novelty': 'New thought',
                    'evidence_quotes': ['Would like to revisit this film']}})
                self.assertEqual(c['response_plan']['should_send'], expected)

    def test_checkin_cannot_fall_back_to_repeated_event_topic(self):
        c = self.context()
        c['checkin_recollection'] = True
        decide(c, lambda *_: {'should_send': True, 'reason': '分享', 'topic': {
            'kind': 'event', 'angle': '分享观影', 'novelty': '新活动', 'evidence_quotes': ['开始看电影']}})
        self.assertFalse(c['response_plan']['should_send'])
