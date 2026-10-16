from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json
import tempfile
import unittest

from life_prototype.clock import TestClock
from life_prototype.config import canonical
from life_prototype.activity_engine import Prototype
from life_prototype.local_configuration import configurations
from life_prototype.resource_library import library, ROOT
from life_prototype.skill_movie import heartbeat, plan, MODE
from life_prototype.cognition import Cognition


class MovieSkillTests(unittest.TestCase):
    def test_reconcile_does_not_push_due_movie_past_captured_decision_time(self):
        from life_prototype import fine_plan
        from life_prototype.coarse_plan_execution import requirement
        from datetime import timedelta
        start = self.clock.now()
        parent = {'id': 'cinema-slot', 'state_type': 'free', 'activity': 'free', 'place': 'home.f2.media',
                  'place_name': '影音区', 'title': '看电影', 'intent': '看电影',
                  'start_at': start.isoformat(), 'end_at': (start + timedelta(hours=2)).isoformat()}
        agenda = {'date': '2026-09-27', 'revision': 1, 'items': [parent]}
        cog = SimpleNamespace(p=self.p, store=self.p.store, clock=self.clock, resource_root=self.root,
                              agenda=Mock())
        cog.agenda.read.return_value = cog.agenda._read.return_value = agenda
        block = {'id': 'movie-block', 'kind': 'watching', 'target': self.key, 'baseline': 0,
                 'duration_seconds': 600, 'start_at': start.isoformat(),
                 'end_at': (start + timedelta(seconds=600)).isoformat()}
        body = {'id': 'plan', 'parent_id': parent['id'], 'parent': parent,
                'agenda_revision': 1, 'created_at': start.isoformat(), 'blocks': [block]}
        fine_plan.initialize(self.p.store)
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state.setdefault('sleep', {})['status'] = 'awake'
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
            db.execute('INSERT INTO life_fine_agendas VALUES(?,?,?,?,?)',
                       ('plan', parent['id'], 'ready', 1, canonical(body)))
        for elapsed in (0.01, 5, 650):
            self.clock.advance(elapsed)
            captured = self.clock.now()
            self.clock.advance(0.001)
            fine_plan.reconcile(cog)
            required = requirement(cog, at=captured)
            self.assertEqual(required['mode'], 'action', required)
            self.assertIn(self.key, required['targets'])
        # No reconciliation may invent playback or viewing progress.
        self.assertFalse(self.p.snapshot()['active'])
        self.assertNotIn(self.key, self.p.snapshot().get('viewing', {}))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.world, self.cog_config, self.sleep_config, self.scheduler_config = configurations()
        self.world['initial']['place'] = 'home.f2.media'
        self.key = 'movie:about_time'
        self.movie = deepcopy(library(movie_place='home.f2.media')['movies'][self.key])
        self.movie['duration_seconds'] = 120  # Short isolated clock fixture.
        self.world['movies'] = {self.key: self.movie}
        self.clock = TestClock('2026-09-27T20:00:00+08:00')
        self.p = Prototype('movies', self.world, self.clock, root=self.root)
        self.cog = SimpleNamespace(p=self.p)

    def command(self, event, operation, **payload):
        return self.p.command(event, self.p.snapshot()['revision'], operation, **payload)

    def start(self, ident='session'):
        self.command('start:'+ident, 'start', activity_id=ident, kind='watching', target=self.key)

    def test_candidates_only_expand_confirmed_catalog_and_have_sourced_durations(self):
        movies = library(movie_place='home.f2.media')['movies']
        catalog = json.loads((ROOT/'libra/movie_knowledge/catalog.json').read_text(encoding='utf8'))
        runtime = json.loads((ROOT/'libra/movie_knowledge/runtimes.json').read_text(encoding='utf8'))
        expected = set()
        for row in catalog['movies']:
            parts = runtime.get('collections', {}).get(row['movie_id'], [row])
            expected.update('movie:'+p['movie_id'] for p in parts)
        self.assertEqual(set(movies), expected)
        self.assertNotIn('movie:before_trilogy', movies)
        self.assertEqual(len(movies), 31)
        self.assertTrue(all(m['duration_seconds'] > 0 and m['duration_source'].startswith('https://')
                            and m['place'] == 'home.f2.media' and m['catalog_status'] == 'watched'
                            for m in movies.values()))
        from life_prototype.fine_plan import resources
        self.p.config['movies'] = movies
        self.assertEqual(len(resources(self.cog, {'state_type': 'free', 'place': 'home.f2.media'}, self.p.snapshot())), 31)

    def test_partial_interrupt_resume_and_duplicate_heartbeat(self):
        self.assertEqual(plan(self.movie, 0, 600)['expected_end']['watched_seconds'], 120)
        self.assertNotIn('viewing', self.p.snapshot())
        self.start()
        self.clock.advance(60)
        heartbeat(self.cog)
        heartbeat(self.cog)
        self.clock.advance(17)
        self.command('stop', 'interrupt', activity_id='session', reason='离开影音区')
        self.assertEqual(self.p.snapshot()['viewing'][self.key], 77)
        self.clock.advance(600)
        self.command('resume', 'resume', activity_id='session')
        self.clock.advance(20)
        heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['viewing_progress'][self.key]['watched_seconds'], 97)
        with self.p.store.connect() as db:
            self.assertIn('00:01:17 / 00:02:00', db.execute("SELECT description FROM events WHERE id='stop'").fetchone()[0])

    def test_completion_capped_and_new_viewing_resets_without_losing_history(self):
        self.start()
        for _ in range(2):
            self.clock.advance(70)
            heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['activities']['session']['status'], 'completed')
        self.assertEqual(self.p.snapshot()['viewing'][self.key], 120)
        self.assertEqual(self.p.snapshot()['viewing_progress'][self.key]['completed_viewings'], 1)
        self.assertFalse(heartbeat(self.cog))
        from life_prototype.fine_plan import resources
        choices = resources(self.cog, {'state_type': 'free', 'place': 'home.f2.media'}, self.p.snapshot())
        self.assertEqual(choices[0]['progress'], 0)
        self.assertTrue(choices[0]['rewatch'])
        self.start('rewatch')
        self.assertEqual(self.p.snapshot()['viewing_progress'][self.key]['watched_seconds'], 0)
        for _ in range(2):
            self.clock.advance(60)
            heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['viewing_progress'][self.key]['completed_viewings'], 2)
        self.assertEqual(self.p.snapshot()['activities']['session']['progress'], 120)

    def test_delayed_heartbeat_counts_twenty_minutes_without_double_counting(self):
        self.p.config['movies'][self.key]['duration_seconds'] = 13260
        self.start()
        self.clock.advance(30)
        heartbeat(self.cog)
        self.clock.advance(20 * 60)
        heartbeat(self.cog)
        heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['viewing'][self.key], 1230)

    def test_restart_does_not_credit_offline_time(self):
        self.start()
        self.clock.advance(30)
        heartbeat(self.cog)
        self.clock.advance(600)
        self.p = Prototype('movies', self.world, self.clock, root=self.root)
        self.command('recover', 'recover', reason='restart')
        self.assertEqual(self.p.snapshot()['viewing'][self.key], 30)
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT kind FROM events WHERE id='recover'").fetchone()[0], 'watching_end')

    def test_delayed_completion_is_capped_and_emits_one_end(self):
        self.start()
        self.clock.advance(1200)
        heartbeat(self.cog)
        self.assertFalse(heartbeat(self.cog))
        state = self.p.snapshot()
        self.assertEqual(state['viewing'][self.key], 120)
        self.assertEqual(state['viewing_progress'][self.key]['completed_viewings'], 1)
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='watching_end'").fetchone()[0], 1)

    def test_delayed_interrupt_and_resume_exclude_paused_time(self):
        self.p.config['movies'][self.key]['duration_seconds'] = 13260
        self.start()
        self.clock.advance(1200)
        self.command('pause', 'interrupt', activity_id='session', reason='离开')
        self.clock.advance(900)
        self.command('resume', 'resume', activity_id='session')
        self.clock.advance(300)
        heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['viewing'][self.key], 1500)

    def test_wrong_location_does_not_credit_watching_time(self):
        self.start()
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['place'] = 'home.f1.living'
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        self.clock.advance(600)
        heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['viewing'][self.key], 0)

    def test_completion_and_end_event_rollback_together(self):
        self.start()
        self.clock.advance(60)
        heartbeat(self.cog)
        self.clock.advance(60)
        with patch.object(self.p, '_commit_locked', side_effect=RuntimeError('interrupted commit')):
            with self.assertRaises(RuntimeError):
                heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['viewing'][self.key], 60)
        heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['activities']['session']['status'], 'completed')
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='watching_end'").fetchone()[0], 1)

    def test_fine_plan_memory_selection_and_deadline_settlement(self):
        from life_prototype import fine_plan as fine_agenda
        parent = {'id': 'cinema-slot', 'state_type': 'free', 'activity': 'free', 'place': 'home.f2.media',
                  'place_name': '影音区', 'title': '看电影', 'intent': '看电影',
                  'start_at': self.clock.now().isoformat(), 'end_at': '2026-09-27T13:00:00+00:00'}
        agenda = {'date': '2026-09-27', 'revision': 1, 'current_item': parent, 'items': [parent]}
        cog = SimpleNamespace(p=self.p, store=self.p.store, clock=self.clock, resource_root=self.root,
            persona={}, memory=Mock(), calls=Mock(), agenda=Mock())
        cog.agenda.view.return_value = cog.agenda.read.return_value = cog.agenda._read.return_value = agenda
        cog.memory.retrieve.return_value = []
        cog.calls.ask.return_value = {'blocks': [{'kind': 'watching', 'target': self.key, 'duration_seconds': 600}],
                                     'reason': '继续看电影'}
        with patch.object(fine_agenda, 'reconcile'), patch('life_prototype.coarse_plan_execution.enter_current'):
            self.assertTrue(fine_agenda.prepare(cog))
        self.assertIn('时空恋旅人', cog.memory.retrieve.call_args.args[0])
        self.assertIn('电影 Skill', cog.calls.ask.call_args.args[2]['movie_skill'])
        with self.p.store.connect() as db:
            status, raw = db.execute('SELECT status,body FROM life_fine_agendas').fetchone()
        self.assertEqual(status, 'ready')
        body = json.loads(raw)
        block = body['blocks'][0]
        self.assertEqual(block['viewing_plan']['expected_end']['watched_seconds'], 120)
        self.start()
        # A shortened coarse slot must settle its partial final interval.
        block['end_at'] = '2026-09-27T12:00:45+00:00'
        with self.p.store.connect() as db:
            fine_agenda.bind(db, {'fine_agenda': {'current_item': block, 'plans': [body]}}, self.p.store.read(db))
        self.clock.advance(600)
        with patch.object(fine_agenda, 'reconcile'):
            self.assertTrue(fine_agenda.pause_expired(cog))
        self.assertEqual(self.p.snapshot()['viewing'][self.key], 45)

    def test_event_memory_and_scheduler_ticks_do_not_call_model(self):
        from life_prototype.interaction import Interaction
        from life_prototype.scheduler import Scheduler
        cog = Cognition(self.p, Mock(), self.cog_config)
        scheduler = Scheduler(Interaction(cog, self.sleep_config), self.scheduler_config)
        scheduler.session = 'isolated-session'
        scheduler._open_session()
        self.p.config['movies'][self.key]['duration_seconds'] = 13260
        self.start()
        with self.p.store.connect() as db:
            meta = scheduler._meta(db)
            meta['dirty'] = False
            scheduler._save(db, meta)
        with patch.object(cog.calls, 'ask', side_effect=AssertionError('model called')), \
             patch.object(cog.agenda, 'ensure'), patch.object(scheduler, '_agenda_basis', return_value=None), \
             patch.object(scheduler, '_refresh_daily_routines', return_value=False), \
             patch('life_prototype.coarse_plan_execution.pause_mismatch', return_value=False), \
             patch('life_prototype.coarse_plan_execution.enter_current', return_value=False):
            for delay in (30, 1200):
                self.clock.advance(delay)
                self.assertEqual(scheduler.pump(), 'simulated_viewing')
            self.command('stop', 'interrupt', activity_id='session', reason='leave')
            cog.ingest()
            cog.ingest()
        self.assertEqual(self.p.snapshot()['viewing'][self.key], 1230)
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM life_model_calls').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM life_memories WHERE id IN (?,?)',
                            ('mem:start:session', 'mem:stop')).fetchone()[0], 2)

    def test_legacy_interrupted_viewing_can_resume_under_new_skill(self):
        self.p.config['movies'][self.key].pop('viewing_mode')
        self.start()
        self.command('pause-old', 'interrupt', activity_id='session', reason='upgrade')
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['activities']['session']['progress'] = 30
            state['viewing'] = {self.key: 30}
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        self.p.config['movies'][self.key]['viewing_mode'] = MODE
        self.command('resume-new', 'resume', activity_id='session')
        self.clock.advance(10)
        heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['viewing'][self.key], 40)


if __name__ == '__main__':
    unittest.main()
