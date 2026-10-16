import unittest

from application.contact_decision import decide


class ContactDecisionTests(unittest.TestCase):
    def context(self, *, persistent=False):
        return {
            'response_plan': {'should_send': False, 'reason': 'pending'},
            'delivery_policy': {'can_send': True},
            'unified_event': {'source': 'scheduled_checkin'},
            'initiative_policy': {'persistent_silence_contact': persistent},
            'recent_assistant_replies': [],
            'decision_recent_messages': [],
        }

    def test_ordinary_checkin_may_still_choose_silence(self):
        context = self.context()
        decide(context, lambda *_: {'should_send': False, 'reason': 'nothing_new'})
        self.assertFalse(context['response_plan']['should_send'])

    def test_empty_memory_checkin_reaches_decision(self):
        context = self.context()
        context['memory_context'] = {'memories': []}
        calls = []
        def model(*args):
            calls.append(args)
            return {'should_send': False, 'reason': 'nothing_new'}
        decide(context, model)
        self.assertTrue(calls)
        self.assertNotEqual(context['response_plan']['reason'], 'no_eligible_recollection')

    def test_requested_report_considers_conversation_and_cancellation(self):
        context = self.context()
        context['unified_event']['source'] = 'libra_life_state'
        context['requested_life_report'] = 'meal'
        context['decision_recent_messages'] = [{'role': 'user', 'content': '今天不用报备了', 'created_at': '2026-10-10T20:00:00'}]
        context['reporting_evidence'] = [{'role': 'user', 'content': '到了告诉我'}]
        def model(stage, prompt):
            self.assertIn('今天不用报备了', prompt)
            self.assertIn('到了告诉我', prompt)
            self.assertIn('preferred_life_report', prompt)
            return {'should_send': False, 'reason': 'report_cancelled'}
        decide(context, model)
        self.assertFalse(context['response_plan']['should_send'])
        self.assertEqual(context['response_plan']['reason'], 'report_cancelled')

    def test_older_agreement_can_ground_fulfillment_topic(self):
        context = self.context()
        context['unified_event'] = {'source': 'libra_life_state', 'description': '左然到达了律所'}
        context['reporting_evidence'] = [{'role': 'user', 'content': '到律所跟我说一声'}]
        decide(context, lambda *_: {'should_send': True, 'reason': 'fulfill_agreement',
               'topic': {'kind': 'event', 'angle': 'arrival report', 'novelty': 'actual arrival',
                         'evidence_quotes': ['到律所跟我说一声', '左然到达了律所']}})
        self.assertTrue(context['response_plan']['should_send'])

    def test_requested_report_respects_hard_boundary(self):
        context = self.context()
        context['unified_event']['source'] = 'libra_life_state'
        context['requested_life_report'] = 'home_arrival'
        context['delivery_policy'] = {'can_send': False, 'suppression_reason': 'sleeping'}
        decide(context, lambda *_: self.fail('blocked report must not call model'))
        self.assertFalse(context['response_plan']['should_send'])
        self.assertEqual(context['response_plan']['reason'], 'sleeping')

    def test_persistent_silence_prefers_natural_contact(self):
        context = self.context(persistent=True)
        decide(context, lambda *_: {'should_send': False, 'reason': 'too_cautious'})
        self.assertTrue(context['response_plan']['should_send'])
        self.assertEqual(context['response_plan']['reason'], 'persistent_silence_natural_contact')

    def test_hard_delivery_boundary_still_wins(self):
        context = self.context(persistent=True)
        context['delivery_policy'] = {'can_send': False, 'suppression_reason': 'policy_blocked'}
        decide(context, lambda *_: {'should_send': True, 'reason': 'ignored'})
        self.assertFalse(context['response_plan']['should_send'])
        self.assertEqual(context['response_plan']['reason'], 'policy_blocked')


if __name__ == '__main__':
    unittest.main()
