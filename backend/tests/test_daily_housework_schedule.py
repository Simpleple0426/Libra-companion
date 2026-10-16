import json
import unittest
from datetime import datetime, timedelta

from life_prototype.coarse_plan import generate, RULES_PATH, LOCAL
from life_prototype.local_configuration import configurations
from life_prototype.skill_housework import routine, steps_for


class DailyHouseworkScheduleTests(unittest.TestCase):
    def test_work_and_rest_days_reserve_executable_chores_before_leisure(self):
        config = configurations()[0]
        rules = json.loads(RULES_PATH.read_text(encoding='utf-8'))
        state = {'place': 'home.f2.bedroom', 'activities': {}}
        for offset in range(28):
            now = datetime(2026, 10, 1, 4, tzinfo=LOCAL) + timedelta(days=offset)
            for day_type in ('workday', 'rest_day'):
                with self.subTest(day=now.date(), day_type=day_type):
                    plan = generate(config, state, now, {'day_type': day_type}, rules)
                    chores = [i for i in plan['items'] if routine(i)]
                    self.assertEqual(len(chores), 1)
                    item = chores[0]
                    self.assertEqual(item['intent'], '家务')
                    self.assertEqual(item['coarse_place'], 'home')
                    self.assertEqual(datetime.fromisoformat(item['start_at']).strftime('%H:%M'), '19:10')
                    self.assertGreaterEqual(
                        datetime.fromisoformat(item['end_at']) - datetime.fromisoformat(item['start_at']),
                        timedelta(minutes=15))
                    steps, reason = steps_for(config, state, item)
                    self.assertTrue(steps, reason)
                    for previous, following in zip(plan['items'], plan['items'][1:]):
                        self.assertLessEqual(datetime.fromisoformat(previous['end_at']),
                                             datetime.fromisoformat(following['start_at']))


if __name__ == '__main__':
    unittest.main()
