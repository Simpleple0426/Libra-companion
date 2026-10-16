import json
import unittest
from copy import deepcopy
from datetime import datetime, timedelta

from life_prototype.coarse_plan_schema import pack, unpack, detail_kinds, intent
from life_prototype.coarse_plan import generate, RULES_PATH, LOCAL
from life_prototype.daily_obligations import day_fact, status
from life_prototype.local_configuration import configurations


class CoarseIntentTests(unittest.TestCase):
    def test_room_media_preferences_preserve_housework_and_adapted_movies(self):
        self.assertEqual(intent({'state_type': 'free', 'from_location': '影音区'}), '看电影')
        self.assertEqual(intent({'state_type': 'free', 'from_location': '客厅'}), '看电视')
        for activity in ('tidy', 'housework', 'household_tidy'):
            self.assertEqual(intent({'state_type': 'free', 'place_name': '客厅', 'activity': activity}), '家务')
        self.assertEqual(intent({'state_type': 'free', 'place_name': '客厅', 'activity': 'watch_movie'}), '看电影')
        self.assertEqual(intent({'state_type': 'resting', 'from_location': '客厅'}), '休息')

    def setUp(self):
        self.config = configurations()[0]
        self.state = {'place': 'home.f1.living', 'activities': {}, 'commitments': [], 'meals': {}}
        self.rules = json.loads(RULES_PATH.read_text(encoding='utf8'))

    def agenda(self, now):
        return generate(self.config, self.state, now, day_fact(now, None), self.rules)

    def test_month_of_plans_has_one_evening_shower_and_awake_bedtime(self):
        before = deepcopy(self.state)
        for offset in range(30):
            now = datetime(2026, 9, 27, 4, tzinfo=LOCAL) + timedelta(days=offset)
            with self.subTest(day=now.date()):
                body = self.agenda(now)
                showers = [i for i in body['items'] if i['intent'] == '洗澡']
                self.assertEqual(len(showers), 1)
                self.assertGreaterEqual(datetime.fromisoformat(showers[0]['start_at']).hour, 18)
                self.assertEqual(showers[0]['place'], 'home.f2.bathroom')
                bedtime = [i for i in body['items'] if i['intent'] == '准备睡觉']
                self.assertTrue(bedtime)
                self.assertTrue(all(i['state_type'] == 'free' and i['place'] == 'home.f2.bedroom' for i in bedtime))
                self.assertEqual(pack(unpack(pack(body))), pack(body))
        self.assertEqual(self.state, before)

    def test_soft_intent_does_not_restrict_free_resources(self):
        body = self.agenda(datetime(2026, 9, 27, 4, tzinfo=LOCAL))
        home = next(i for i in body['items'] if i['intent'] == '家中活动')
        self.assertEqual(home['activity'], 'home_activity')
        self.assertTrue(any(i['intent'] == '用餐' for i in body['items']))
        self.assertFalse(any(i['intent'] == '备餐' for i in body['items']))
        self.assertTrue(any(i['intent'] == '晚间活动' for i in body['items']))

    def test_home_shower_varies_stably_and_can_precede_more_leisure(self):
        starts=set();resumed=False
        for offset in range(30):
            now=datetime(2026,9,27,4,tzinfo=LOCAL)+timedelta(days=offset)
            body=self.agenda(now)
            self.assertEqual(body,self.agenda(now))
            shower=next(i for i in body['items'] if i['intent']=='洗澡')
            starts.add(datetime.fromisoformat(shower['start_at']).strftime('%H:%M'))
            resumed |= any(i['intent']=='晚间活动' and i['start_at']>=shower['end_at']
                           for i in body['items'])
            self.assertTrue(any(i['activity']=='bedtime_wash' for i in body['items']))
            for previous,following in zip(body['items'],body['items'][1:]):
                self.assertLessEqual(datetime.fromisoformat(previous['end_at']),
                                     datetime.fromisoformat(following['start_at']))
        self.assertGreater(len(starts),1)
        self.assertTrue(resumed)

    def test_early_configuration_cannot_enable_daytime_shower(self):
        self.config['daily_routines']['shower']['available_after'] = '08:00'
        now = datetime(2026, 9, 27, 12, tzinfo=LOCAL)
        shower = next(r for r in status(self.config, self.state, now) if r['kind'] == 'shower')
        self.assertEqual(shower['status'], 'upcoming')
        self.assertEqual(datetime.fromisoformat(shower['available_after']).hour, 18)

    def test_completed_shower_is_not_planned_again(self):
        self.state['activities']['done'] = {'kind': 'showering', 'target': 'routine:2026-09-27:shower', 'status': 'completed'}
        body = self.agenda(datetime(2026, 9, 27, 19, tzinfo=LOCAL))
        self.assertFalse(any(i['intent'] == '洗澡' for i in body['items']))

    def test_reflow_preserves_intents_and_evening_routine(self):
        from life_prototype.coarse_plan_updates import reflow
        now = datetime(2026, 9, 27, 4, tzinfo=LOCAL)
        body = self.agenda(now)
        revised = reflow(body, {'appointments': [], 'cancelled': []}, self.state, self.config, now)
        # The committing caller assigns IDs to newly rebuilt movement rows.
        for index, item in enumerate(revised['items']):
            item['id'] = f'revised:{index}'
        revised = unpack(pack(revised))
        shower = next(i for i in revised['items'] if i['intent'] == '洗澡')
        self.assertGreaterEqual(datetime.fromisoformat(shower['start_at']).hour, 18)
        self.assertTrue(any(i['intent'] in {'家中活动','晚间活动'} for i in revised['items']))

    def test_old_format_remains_readable_without_inventing_intent(self):
        body = pack(self.agenda(datetime(2026, 9, 27, 4, tzinfo=LOCAL)))
        body['version'] = 'coarse-state-v1'
        for item in body['items']:
            item.pop('intent')
        old = deepcopy(body)
        restored = unpack(body)
        self.assertEqual(body, old)
        self.assertTrue(all('intent' not in i for i in restored['items']))
        self.assertTrue(any(i['activity'] == 'shower' for i in restored['items']))


if __name__ == '__main__':
    unittest.main()
