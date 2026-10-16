from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import re
import unittest

from life_prototype.coarse_plan import RULES_PATH as CONFIG_PATH, generate, LOCAL
from life_prototype.local_configuration import configurations
from life_prototype.meal_places import configured
from life_prototype.skill_router import select
from life_prototype.coarse_plan_schema import site_id, pack
from datetime import datetime


class CityScheduleLocationsTests(unittest.TestCase):
    def setUp(self):
        self.rules = json.loads(CONFIG_PATH.read_text(encoding='utf8'))

    def test_pools_match_authoritative_city_document(self):
        document = (CONFIG_PATH.parents[2] / 'docs/character/左然城市地点清单.md').read_text(encoding='utf8')
        expected = {}
        headings = {'法院': 'courts', '检察院': 'procuratorates', '警局': 'police',
                    '工作走访地点': 'work_visits', '生鲜与便利店': 'groceries',
                    '商场与商业街': 'shopping', '市集': 'markets', '早餐店': 'breakfast_shops',
                    '餐厅': 'restaurants', '咖啡与饮品': 'coffee_and_drinks'}
        for heading, key in headings.items():
            section = re.search(r'^### ' + heading + r'（\d+）\s*\n(.*?)(?=^##|\Z)', document, re.M | re.S).group(1)
            expected[key] = [re.sub(r'（新增）$', '', name) for name in re.findall(r'^- (.+)$', section, re.M)]
        for key in ('swimming', 'gym', 'shooting', 'bookstores', 'cinemas', 'theatre', 'bars', 'walks'):
            names = re.search(r'^\| `' + key + r'` \| (.*?) \|', document, re.M).group(1)
            expected[key] = names.split('、')
        for key, names in expected.items():
            self.assertEqual(self.rules['locations'][key], names, key)
            self.assertEqual(len(names), len(set(names)), key)
        entries = [name for names in expected.values() for name in names]
        self.assertEqual(len(entries), 105)
        self.assertEqual(len(set(entries)), 104)
        self.assertEqual(self.rules['locations']['relaxation'], [])

    def test_skill_plans_route_all_non_travel_slots_and_use_city_catalog(self):
        config=configured(configurations()[0],self.rules)
        state={'place':'home.f1.living','activities':{},'commitments':[]}
        seen=set()
        for offset in range(30):
            now=datetime(2026,9,27,4,tzinfo=LOCAL)+timedelta(days=offset)
            body=generate(config,state,now,{'day_type':'workday' if now.weekday()<5 else 'rest_day'},self.rules)
            self.assertEqual(body['source'],'skill_coarse_planner')
            self.assertNotIn('legacy_generator',body)
            for item in body['items']:
                self.assertLess(item['start_at'],item['end_at'])
                if item['state_type']=='commuting':continue
                self.assertIsNotNone(select(item));seen.add(select(item))
                self.assertNotEqual(item['state_type'],'sleeping')
            for item in body['items']:
                if item['state_type']=='commuting':
                    self.assertNotEqual(site_id(item['place']),site_id(item['destination']))
            stored=pack(body)
            self.assertTrue(all(not str(i['location_id']).startswith(('home.','firm.')) for i in stored['items']))
        self.assertIn('work',seen)
        self.assertIn('dining',seen)
        self.assertIn('home_activity',seen)
