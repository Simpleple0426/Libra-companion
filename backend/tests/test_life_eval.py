"""Check the evaluator cannot award success to plausible but wrong outcomes."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.life_cases import CASES
from evals.life_grading import grade_turn, summarize, same_time


class LifeEvalGraderTests(unittest.TestCase):
    def setUp(self):
        self.before = {'state': {}, 'agenda': {'revision': 1, 'items': []}}
        self.review = {'status': 'none', 'message_id': 'app:test:ordinary'}
        self.context = {'daily_agenda_review': self.review.copy()}

    def test_no_action_requires_terminal_receipt(self):
        grade = grade_turn({'status': 'none', 'unchanged': True}, self.before,
                           self.before, {'status': 'pending'}, {})
        self.assertFalse(grade['passed'])
        self.assertIn('terminal_outcome', grade['failed_checks'])

    def test_no_action_rejects_hidden_write(self):
        after = deepcopy(self.before)
        after['state']['companionships'] = [{'id': 'unwanted', 'status': 'active'}]
        grade = grade_turn({'status': 'none', 'unchanged': True}, self.before,
                           after, self.review, self.context)
        self.assertFalse(grade['passed'])
        self.assertIn('no_unrequested_write', grade['failed_checks'])

    def test_wrong_time_and_duplicate_items_fail(self):
        wanted = {'activity': 'reading', 'start_at': '2026-09-28T16:00:00+08:00',
                  'end_at': '2026-09-28T17:00:00+08:00'}
        expected = {'status': 'none', 'item': wanted}
        after = deepcopy(self.before)
        after['agenda']['items'] = [{**wanted, 'start_at': '2026-09-28T15:00:00+08:00'}]
        self.assertFalse(grade_turn(expected, self.before, after, self.review, self.context)['passed'])
        after['agenda']['items'] = [wanted, wanted.copy()]
        self.assertFalse(grade_turn(expected, self.before, after, self.review, self.context)['passed'])
        after['agenda']['items'] = [wanted]
        self.assertTrue(grade_turn(expected, self.before, after, self.review, self.context)['passed'])

    def test_stale_other_message_receipt_fails(self):
        self.context['daily_agenda_review']['message_id'] = 'previous-message'
        self.assertFalse(grade_turn({'status': 'none'}, self.before, self.before,
                                    self.review, self.context)['passed'])

    def test_timezones_and_unspecified_end(self):
        self.assertTrue(same_time('2026-09-28T16:00:00+08:00', '2026-09-28T08:00:00+00:00'))
        self.assertFalse(same_time(None, '2026-09-28T08:00:00+00:00'))

    def test_outbox_must_correlate_to_current_message(self):
        self.review['status'] = 'clarify'
        self.context['daily_agenda_review'] = self.review.copy()
        after = deepcopy(self.before)
        after['outbox'] = [{'id': 'unrelated', 'detail': {'source_message': 'old'}}]
        self.assertFalse(grade_turn({'status': 'clarify'}, self.before, after, self.review, self.context)['passed'])
        after['outbox'][0]['detail']['source_message'] = self.review['message_id']
        self.assertTrue(grade_turn({'status': 'clarify'}, self.before, after, self.review, self.context)['passed'])

    def test_errors_stay_in_denominator_and_missing_repeats_not_stable(self):
        results = [dict(case_id='one', category='explicit', execution_status='evaluated',
                        passed=True, duration_seconds=1, model_calls=2),
                   dict(case_id='two', category='explicit', execution_status='error', passed=False)]
        summary = summarize(results, {'runs': 6, 'cases': 2, 'repeats': 3})
        self.assertEqual(summary['success_rate'], .5)
        self.assertEqual(summary['all_repeats_passed_cases'], 0)
        self.assertIsNone(summary['false_success_reply_rate'])

    def test_preparation_has_no_quality_score(self):
        summary = summarize([dict(case_id='one', category='explicit', execution_status='prepared', passed=None)],
                            {'runs': 1, 'cases': 1, 'repeats': 1})
        self.assertIsNone(summary['success_rate'])
        self.assertEqual(summary['by_category']['explicit']['errors'], 0)

    def test_model_message_ids_do_not_expose_case_labels(self):
        from evals.run_life_eval import message_id
        ident = message_id('protected_dinner', 1, 0)
        self.assertRegex(ident, r'^m_[0-9a-f]{24}$')
        self.assertEqual(ident, message_id('protected_dinner', 1, 0))
        self.assertNotEqual(ident, message_id('protected_dinner', 2, 0))

    def test_suite_is_unique_and_has_concrete_oracles(self):
        self.assertEqual(len(CASES), 30)
        self.assertEqual(len({c['id'] for c in CASES}), 30)
        self.assertEqual(len({c['category'] for c in CASES}), 6)
        for case in CASES:
            for turn in case['turns']:
                self.assertTrue(turn['text'])
                self.assertIn('status', turn['expected'])
                self.assertGreater(len(turn['expected']), 1)


if __name__ == '__main__':
    unittest.main()
