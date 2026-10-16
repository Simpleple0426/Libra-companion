from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
import json
import tempfile
import unittest

from life_prototype.clock import TestClock
from life_prototype.activity_engine import Prototype
from life_prototype.local_configuration import configurations
from life_prototype.cognition import Cognition
from life_prototype.skill_reading import imported_book, heartbeat, plan, migrate_progress, position
from life_prototype.config import canonical


class ReadingSkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root/'book'
        self.directory.mkdir()
        for name in ('a.txt', 'b.txt'):
            (self.directory/name).write_text('正文不应被读取', encoding='utf8')
        self.manifest = {'bookId': 'test', 'title': '无人生还', 'sourceHash': 'v1', 'chunks': [
            {'id': 'a', 'path': 'a.txt', 'charCount': 800, 'sectionTitle': '第一章'},
            {'id': 'b', 'path': 'b.txt', 'charCount': 1200, 'sectionTitle': '第二章'}]}
        self.key, self.book = imported_book(self.directory, self.manifest)
        self.world, self.cog_config, *_ = configurations()
        self.world['initial']['place'] = 'home.f2.study'
        self.world['books'] = {self.key: self.book}
        self.world['objects'][self.book['object']] = {'name': '无人生还', 'parent': 'home.f2.study',
            'status': 'confirmed', 'source': 'imported_book:local'}
        self.clock = TestClock('2026-09-27T09:00:00+08:00')
        self.p = Prototype('reading', self.world, self.clock, root=self.root)
        self.cog = SimpleNamespace(p=self.p)

    def command(self, event, operation, **payload):
        return self.p.command(event, self.p.snapshot()['revision'], operation, **payload)

    def start(self):
        self.command('start', 'start', activity_id='session', kind='reading', target=self.key)

    def test_import_checks_files_without_reading_prose(self):
        with patch.object(Path, 'read_text', side_effect=AssertionError('prose read')):
            self.assertEqual(imported_book(self.directory, self.manifest), (self.key, self.book))
        self.assertNotIn('text', self.book)
        bad = deepcopy(self.manifest)
        bad['chunks'][0]['path'] = '../outside.txt'
        self.assertIsNone(imported_book(self.directory, bad))
        (self.directory/'b.txt').unlink()
        self.assertIsNone(imported_book(self.directory, self.manifest))

    def test_plan_is_forecast_and_interrupt_settles_partial_time(self):
        forecast = plan(self.book, 0, 180, self.world)
        self.assertEqual(forecast['expected_end']['offset'], 1200)
        self.assertEqual(forecast['expected_end']['chapter'], '第二章')
        self.assertEqual(self.p.snapshot()['reading'], {})
        self.start()
        self.clock.advance(60)
        self.assertTrue(heartbeat(self.cog))
        self.assertEqual(self.p.snapshot()['activities']['session']['progress'], 400)
        heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['activities']['session']['progress'], 400)
        self.clock.advance(15)
        self.command('stop', 'interrupt', activity_id='session', reason='离开书房')
        state = self.p.snapshot()
        self.assertEqual(state['reading_progress'][self.key]['offset'], 500)
        self.assertIsNone(state['active'])
        with self.p.store.connect() as db:
            events = db.execute('SELECT kind,description FROM events ORDER BY rowid').fetchall()
        self.assertEqual(events[0], ('reading_start', '左然正在阅读《无人生还》（第一章（约0%））'))
        self.assertIn('左然结束阅读《无人生还》，进度：第一章', events[-1][1])
        self.clock.advance(600)
        self.command('resume', 'resume', activity_id='session')
        self.clock.advance(60)
        heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['reading_progress'][self.key]['offset'], 900)
        self.assertEqual(position(self.book, 900)['chapter'], '第二章')

    def test_restart_keeps_heartbeat_progress_without_offline_credit(self):
        self.start()
        self.clock.advance(60)
        heartbeat(self.cog)
        self.clock.advance(3600)
        self.p = Prototype('reading', self.world, self.clock, root=self.root)
        self.command('restart', 'recover', reason='restart')
        self.assertEqual(self.p.snapshot()['reading_progress'][self.key]['offset'], 400)
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT kind FROM events WHERE id='restart'").fetchone()[0], 'reading_end')

    def test_deadline_and_completion_are_bounded(self):
        self.start()
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['activities']['session']['reading_deadline'] = '2026-09-27T01:00:30+00:00'
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        self.clock.advance(60)
        heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['activities']['session']['progress'], 200)
        self.command('stop', 'interrupt', activity_id='session', reason='budget')
        self.command('resume', 'resume', activity_id='session')
        for _ in range(5):
            self.clock.advance(60)
            heartbeat(self.cog)
        state = self.p.snapshot()
        self.assertEqual(state['activities']['session']['status'], 'completed')
        self.assertEqual(state['reading_progress'][self.key]['offset'], 2000)
        self.assertFalse(heartbeat(self.cog))

    def test_events_and_checkpoint_use_no_model(self):
        class NoModel:
            def complete(self, *args, **kwargs):
                raise AssertionError('reading should not call model')
        cog = Cognition(self.p, NoModel(), config=self.cog_config)
        with patch.object(cog.calls, 'ask', side_effect=AssertionError('model called')):
            self.start()
            cog.ingest()
            self.clock.advance(30)
            self.assertFalse(cog.read_checkpoint('checkpoint')['model_called'])
            self.command('stop', 'interrupt', activity_id='session', reason='leave')
            cog.ingest()
            cog.ingest()
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM life_observations WHERE processed=0').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM life_model_calls').fetchone()[0], 0)

    def test_legacy_migration_preserves_old_progress_and_is_idempotent(self):
        old = {'legacy': {'library_id': self.book['library_id'], 'version': 'old'}}
        state = {'reading': {'legacy:old': 600}}
        migrate_progress(state, old, {self.key: self.book})
        self.assertEqual(state['reading']['legacy:old'], 600)
        self.assertEqual(state['reading_progress'][self.key]['offset'], 600)
        after = deepcopy(state)
        migrate_progress(state, old, {self.key: self.book})
        self.assertEqual(state, after)

    def test_fine_plan_selects_book_from_memory_and_binds_actual_range(self):
        from life_prototype import fine_plan as fine_agenda
        parent = {'id': 'coarse-reading', 'activity': 'free', 'state_type': 'free', 'place': 'home.f2.study',
                  'place_name': '书房', 'title': '阅读', 'intent': '阅读',
                  'start_at': self.clock.now().isoformat(), 'end_at': '2026-09-27T02:00:00+00:00'}
        agenda = {'date': '2026-09-27', 'revision': 1, 'current_item': parent, 'items': [parent]}
        cog = SimpleNamespace(p=self.p, store=self.p.store, clock=self.clock, resource_root=self.root,
            persona={}, memory=Mock(), calls=Mock(), agenda=Mock())
        cog.agenda.view.return_value = agenda
        cog.agenda.read.return_value = agenda
        cog.agenda._read.return_value = agenda
        cog.memory.retrieve.return_value = [{'description': '上次阅读的书'}]
        cog.calls.ask.return_value = {'blocks': [{'kind': 'reading', 'target': self.key,
                                                 'duration_seconds': 600}], 'reason': '继续阅读'}
        with patch.object(fine_agenda, 'reconcile'), patch('life_prototype.coarse_plan_execution.enter_current'):
            self.assertTrue(fine_agenda.prepare(cog))
        payload = cog.calls.ask.call_args.args[2]
        self.assertIn('无人生还', cog.memory.retrieve.call_args.args[0])
        self.assertIn('阅读 Skill', payload['reading_skill'])
        self.assertNotIn('structure', payload['resources'][0])
        self.assertNotIn('text', payload['resources'][0])
        with self.p.store.connect() as db:
            status, raw = db.execute('SELECT status,body FROM life_fine_agendas').fetchone()
        self.assertEqual(status, 'ready')
        body = json.loads(raw)
        block = body['blocks'][0]
        self.assertEqual(block['reading_plan']['start']['offset'], 0)
        self.assertEqual(block['reading_plan']['expected_end']['offset'], 2000)
        self.start()
        with self.p.store.connect() as db:
            fine_agenda.bind(db, {'fine_agenda': {'current_item': block, 'plans': [body]}}, self.p.store.read(db))
        self.assertEqual(self.p.snapshot()['activities']['session']['reading_deadline'], block['end_at'])
        self.assertEqual(self.p.snapshot()['activities']['session']['progress'], 0)

    def test_scheduler_start_refreshes_library_before_pending_jobs(self):
        from life_prototype.interaction import Interaction
        from life_prototype.scheduler import Scheduler
        folder = self.root/'backend/private_reading/reading/books/local'
        folder.mkdir(parents=True)
        (folder/'manifest.json').write_text(json.dumps(self.manifest), encoding='utf8')
        for name in ('a.txt', 'b.txt'):
            (folder/name).write_text('content', encoding='utf8')
        cog = Cognition(self.p, Mock(), config=self.cog_config)
        cog.resource_root = self.root
        _, _, sleep_config, scheduler_config = configurations()
        scheduler = Scheduler(Interaction(cog, sleep_config), scheduler_config)
        scheduler.session = 'startup'
        with patch.object(cog.calls, 'ask', side_effect=AssertionError('model called')):
            scheduler._open_session()
        self.assertEqual(self.p.config['books'][self.key]['manifest_path'], str(folder/'manifest.json'))
        self.assertIn(self.key+':'+self.book['version'], self.p.snapshot()['reading'])


if __name__ == '__main__':
    unittest.main()
