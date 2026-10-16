from datetime import datetime, timedelta
import unittest
from application.user_activity_context import recent, block


class UserActivityContextTests(unittest.TestCase):
    def test_filters_charging_old_future_and_invalid_events(self):
        now = datetime(2026, 10, 13, 16)
        rows = [dict(occurred_at='2026-10-13T15:00:00', description='开始组会', event_type='manual_timeline'),
                dict(occurred_at='2026-10-13T15:01:00', description='手机开始充电了'),
                dict(occurred_at='2026-10-12T12:00:00', description='旧活动'),
                dict(occurred_at='2026-10-14T15:00:00', description='未来安排'),
                dict(occurred_at='bad', description='坏时间')]
        result = recent(rows, now)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['description'], '开始组会')
        self.assertIn('未记录结束也不证明仍在进行', block(result))

    def test_manual_entries_have_priority_and_limit_is_eight(self):
        now = datetime(2026, 10, 13, 16)
        rows = [dict(occurred_at=(now-timedelta(minutes=i)).isoformat(),
                     description=str(i), event_type='room') for i in range(10)]
        rows.append(dict(occurred_at=(now-timedelta(hours=10)).isoformat(),
                         description='手动活动', event_type='manual_timeline'))
        result = recent(rows, now)
        self.assertEqual(len(result), 8)
        self.assertEqual(result[0]['description'], '手动活动')

    def test_timezone_and_no_activity(self):
        result = recent([dict(occurred_at='2026-10-13T07:00:00Z', description='会议')], datetime(2026,10,13,16))
        self.assertEqual(result[0]['occurred_at'], '2026-10-13T15:00:00')
        self.assertEqual(block([]), '')
