from copy import deepcopy
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from life_prototype.home_catalog import catalog, apply_to_world
from life_prototype.home_world import path
from life_prototype.local_configuration import configurations
from life_prototype.coarse_plan import generate, RULES_PATH, LOCAL
from life_prototype.daily_obligations import day_fact
from scripts.build_home_catalog import build
from scripts.import_home_catalog import migrate, stopped_worker


class HomeCatalogTests(unittest.TestCase):
    def test_catalog_covers_document_and_all_rooms_are_reachable(self):
        self.assertEqual(catalog(), build())
        world = configurations()[0]
        self.assertEqual(len(catalog()['places']), 16)
        self.assertEqual(len(catalog()['objects']), 142)
        for ident in catalog()['places']:
            if ident != 'home':
                self.assertTrue(path(world, 'home.f1.living', ident))
        self.assertEqual(path(world, 'home.f1.living', 'home.f1.balcony'),
                         ['home.f1.living', 'home.f1.balcony'])
        names = {obj['name'] for obj in world['objects'].values()}
        self.assertTrue({'微蒸烤一体机', '洗碗机', '投影仪', '跑步机', '浴缸', '烘干机',
                         '红豆项链', '小熊公仔', '大雁戒托', '家庭 Wi-Fi'} <= names)
        self.assertEqual(world['initial']['inventory'], {})
        self.assertEqual(world['initial']['available_tools'], [])

    def test_import_does_not_reset_moved_object_or_unknown_states(self):
        world = configurations()[0]
        ident = next(k for k,v in world['objects'].items() if v['name'] == '小熊公仔')
        world['objects'][ident]['parent'] = 'home.f1.living'
        self.assertEqual(apply_to_world(world), world)
        for obj in catalog()['objects'].values():
            self.assertIsNone(obj['quantity'])
            self.assertIsNone(obj['dynamic_state']['power'])

    def test_schedule_defers_home_choices_and_uses_real_media_resources(self):
        world = configurations()[0]
        state = {'place': 'home.f1.living', 'activities': {}, 'commitments': [], 'meals': {}}
        now = datetime(2026, 9, 27, 4, tzinfo=LOCAL)
        body = generate(world, state, now, day_fact(now, None), json.loads(RULES_PATH.read_text(encoding='utf8')))
        from life_prototype.skill_home_activity import routine, _choices
        home = [i for i in body['items'] if i.get('intent') == '家中活动']
        self.assertTrue(home)
        self.assertTrue(all(routine(i) for i in home))
        # Rooms are usable resources, not mandatory stops every day. The
        # home skill selects an actual library item after coarse planning.
        world['movies'] = {'fixture': {'place': 'home.f2.media', 'available': True}}
        movies = [c for c in _choices(world, home[0]) if c['choice'] == 'movie']
        self.assertEqual([(c['place'], c['resource_id']) for c in movies], [('home.f2.media', 'fixture')])
        world['movies']['fixture']['available'] = False
        self.assertFalse(any(c['choice'] == 'movie' for c in _choices(world, home[0])))

    def test_offline_migration_preserves_actor_and_history_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            database = directory/'prototype.sqlite3'
            world = configurations()[0]
            world['objects'] = {}
            world.pop('household_catalog')
            current = {'revision': 7, 'place': 'home.f2.study', 'reading': {'book': 50},
                       'watching': {'movie': 300}, 'activities': {'old': {'status': 'interrupted'}}}
            with closing(sqlite3.connect(database)) as db, db:
                db.executescript('CREATE TABLE life_state(name TEXT PRIMARY KEY,id INT,body TEXT);'
                    'CREATE TABLE life_evidence(category TEXT,id TEXT,body TEXT,PRIMARY KEY(category,id));'
                    'CREATE TABLE events(id TEXT); INSERT INTO events VALUES("prior");')
                for name,value in {'world':world,'current':current,'scheduler':{},'resources':{
                    'movies':{'movie':{'source':'confirmed_movie_library','place':'home.f1.living'}}}}.items():
                    db.execute('INSERT INTO life_state VALUES(?,1,?)',(name,json.dumps(value)))
            with stopped_worker(directory):
                with self.assertRaises(OSError):
                    migrate(database, directory/'locked-backup.sqlite3')
            report = migrate(database, directory/'backup.sqlite3')
            self.assertTrue(report['changed'])
            self.assertEqual(report['movies_at_media'], 1)
            with closing(sqlite3.connect(database)) as db:
                after = json.loads(db.execute("SELECT body FROM life_state WHERE name='current'").fetchone()[0])
                expected = deepcopy(current); expected['revision'] += 1
                self.assertEqual(after, expected)
                self.assertEqual(db.execute('SELECT * FROM events').fetchall(), [('prior',)])
            self.assertFalse(migrate(database, directory/'second-backup.sqlite3')['changed'])
