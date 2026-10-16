from datetime import datetime, timedelta
import unittest
from zoneinfo import ZoneInfo

from application.life_contact_policy import availability, candidate, report_kind, REPORT_GAP_SECONDS


class LifeContactPolicyTests(unittest.TestCase):
    def test_reports_require_actual_milestones(self):
        self.assertEqual(report_kind({'kind': 'meal_start'}), 'meal')
        self.assertEqual(report_kind({'kind': 'work_start'}), 'work')
        self.assertEqual(report_kind({'kind': 'arrived', 'event': '左然回到了家'}), 'home_arrival')
        self.assertIsNone(report_kind({'kind': 'moving_start', 'event': '左然准备回家'}))
        self.assertIsNone(report_kind({'kind': 'arrived', 'event': '左然到了书房'}))
        self.assertEqual(report_kind({'kind': 'arrived', 'event': '左然到达了忒弥斯律所',
                                     'detail': {'hierarchy': 'coarse_location_boundary'}}), 'work_arrival')
        self.assertIsNone(report_kind({'kind': 'arrived', 'event': '左然到达了律所办公室',
                                      'detail': {'hierarchy': 'fine_location'}}))
        actual_arrival = {'id': 'coarse-location:committed:0', 'kind': 'arrived',
                          'event': '左然到达了忒弥斯律所', 'detail': {'activity_id': None}}
        self.assertTrue(candidate(actual_arrival)[0])
        self.assertEqual(report_kind(actual_arrival), 'work_arrival')

    def test_reports_and_ordinary_contact_have_no_cooldown(self):
        now = datetime(2026, 10, 10, 18, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
        args = dict(last_sent_at=(now - timedelta(minutes=20)).isoformat(), sent_day=None, sent_count=0)
        self.assertTrue(availability(now, **args)[0])
        self.assertTrue(availability(now, **args, min_gap_seconds=REPORT_GAP_SECONDS)[0])
        args['last_sent_at'] = (now - timedelta(minutes=5)).isoformat()
        self.assertTrue(availability(now, **args, min_gap_seconds=REPORT_GAP_SECONDS)[0])

    def test_room_moves_do_not_enter_contact_review_but_life_nodes_do(self):
        self.assertFalse(candidate({"kind": "arrived", "detail": {"hierarchy": "fine_location"}})[0])
        self.assertTrue(candidate({"kind": "work_start"})[0])
        self.assertTrue(candidate({"kind": "meal_start"})[0])
        self.assertTrue(candidate({"kind": "rest_start"})[0])
        self.assertTrue(candidate({"kind": "companion_update"})[0])

    def test_site_boundaries_and_major_milestones_can_be_reviewed(self):
        boundary = {"kind": "arrived", "detail": {"hierarchy": "coarse_location_boundary"}}
        self.assertTrue(candidate(boundary)[0])
        self.assertTrue(candidate({"kind": "woke"})[0])
        self.assertTrue(candidate({"kind": "reading_completed"})[0])

    def test_recent_send_does_not_block_contact(self):
        now = datetime(2026, 9, 29, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        allowed, reason = availability(
            now,
            last_sent_at=(now - timedelta(seconds=1)).replace(tzinfo=None).isoformat(),
            sent_day="2026-09-29",
            sent_count=2,
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, "available")

    def test_daily_count_has_no_cap(self):
        now = datetime(2026, 9, 30, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertTrue(availability(now, last_sent_at=None, sent_day="2026-09-29", sent_count=5)[0])
        self.assertTrue(availability(now, last_sent_at=None, sent_day="2026-09-30", sent_count=500)[0])


if __name__ == "__main__":
    unittest.main()
