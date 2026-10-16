import unittest
import test_companionship as fixture
from life_prototype.companionship import current, revise


class CompanionStartTimeTests(unittest.TestCase):
    setUp = fixture.CompanionshipTests.setUp
    send = fixture.CompanionshipTests.send

    def test_bare_invitation_clarifies_without_mutating_life(self):
        before = self.p.snapshot()
        result = self.send('invite', '陪我去漫展')
        self.assertEqual(result['status'], 'clarify')
        self.assertEqual(result['missing_fields'], ['start_at'])
        self.assertEqual(self.p.snapshot(), before)
        self.assertEqual(revise(self.cog, result['companion_proposal']), result)

    def test_date_only_cannot_default_to_now_or_invent_a_clock_time(self):
        for index, start in enumerate([None, '2026-09-29T07:00:00+08:00']):
            result = self.send(str(index), '明天陪我去漫展', start_at=start)
            self.assertEqual(result['status'], 'clarify')
        self.assertIsNone(current(self.p.snapshot(), self.clock.now()))

    def test_end_time_does_not_substitute_for_start_time(self):
        result = self.send('invite', '陪我到晚上8点', end_at='2026-09-28T20:00:00+08:00')
        self.assertEqual(result['status'], 'clarify')
        self.assertEqual(result['missing_fields'], ['start_at'])

    def test_explicit_now_can_leave_end_unspecified(self):
        result = self.send('invite', '现在陪我去漫展')
        self.assertEqual(result['status'], 'applied')
        self.assertIsNone(result['companion']['end_at'])

    def test_time_only_followup_uses_original_invitation(self):
        self.send('invite', '陪我去漫展')
        result = self.send('answer', '明天早上7点', context_message_id='invite',
                           start_at='2026-09-29T07:00:00+08:00', title='陪用户逛漫展')
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(result['companion']['status'], 'scheduled')
        self.assertIsNone(result['companion']['end_at'])

    def test_known_context_time_does_not_require_repeating_it(self):
        self.send('context', '明天7点出发，陪我去漫展', start_at=None)
        result = self.send('confirm', '陪我去漫展吧', context_message_id='context',
                           start_at='2026-09-29T07:00:00+08:00')
        self.assertEqual(result['status'], 'applied')

    def test_stale_now_context_does_not_enter_today(self):
        self.send('old', '现在陪我去漫展', start_at='2026-09-29T07:00:00+08:00')
        self.clock.advance(600)
        result = self.send('new', '陪我去漫展吧', context_message_id='old')
        self.assertEqual(result['status'], 'clarify')


if __name__ == '__main__':
    unittest.main()
