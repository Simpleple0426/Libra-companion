import json
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

import test_future_appointments as fixture
from life_prototype.interaction import Interaction
from life_prototype.local_configuration import configurations
from life_prototype.scheduler import Scheduler
from life_prototype.config import canonical


class SchedulerAutoRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture.FutureAppointmentTests.setUp(self)
        _, _, sleep, scheduler = configurations()
        self.s = Scheduler(Interaction(self.cog, sleep), scheduler)

    def row(self, ident):
        with self.p.store.connect() as db:
            return db.execute('SELECT * FROM life_scheduler_jobs WHERE id=?', (ident,)).fetchone()

    def blocked(self, kind='sync', detail=None):
        ident = self.s._job(kind, 'blocked:' + kind, {})
        with self.p.store.connect() as db:
            db.execute("UPDATE life_scheduler_jobs SET status='blocked',attempts=3,receipt=? WHERE id=?",
                       (canonical(detail or {'type': 'TimeoutError', 'detail': 'model timeout'}), ident))
        return ident

    def test_retries_after_persisted_cooldown_and_retains_audit(self):
        ident = self.blocked()
        before = self.p.snapshot()
        self.assertEqual(self.s._run_job(self.row(ident)), 'retry_wait')
        self.clock.advance(30)
        self.s = Scheduler(self.s.chat, self.s.config)
        self.assertEqual(self.s._run_job(self.row(ident)), 'retry_wait')
        self.clock.advance(30)
        self.assertEqual(self.s._run_job(self.row(ident)), 'queued')
        with self.p.store.connect() as db:
            replacement = db.execute('SELECT replacement_job_id FROM life_scheduler_recoveries WHERE blocked_job_id=?', (ident,)).fetchone()[0]
        self.s._execute = Mock(return_value={'observations_absorbed': True})
        self.assertEqual(self.s._run_job(self.row(replacement)), 'worked')
        self.assertEqual(self.row(replacement)[3], 'done')
        self.assertEqual(self.row(ident)[3], 'blocked')
        self.assertEqual(self.p.snapshot(), before)

    def test_backoff_grows_after_repeated_outage(self):
        ident = self.blocked()
        self.s._run_job(self.row(ident)); self.clock.advance(60)
        self.s._run_job(self.row(ident))
        with self.p.store.connect() as db:
            replacement = db.execute('SELECT replacement_job_id FROM life_scheduler_recoveries WHERE blocked_job_id=?', (ident,)).fetchone()[0]
            db.execute("UPDATE life_scheduler_jobs SET status='blocked',attempts=3,receipt='{}' WHERE id=?", (replacement,))
        self.assertEqual(self.s._run_job(self.row(replacement)), 'retry_wait')
        self.clock.advance(60)
        self.assertEqual(self.s._run_job(self.row(replacement)), 'retry_wait')
        self.clock.advance(240)
        self.assertEqual(self.s._run_job(self.row(replacement)), 'queued')

    def test_pending_or_committed_results_are_not_replayed(self):
        ident = self.blocked('read')
        for receipt in (None, '{}'):
            with self.subTest(receipt=receipt):
                with self.p.store.connect() as db:
                    db.execute('INSERT OR REPLACE INTO results VALUES(?,?,?)', (ident + ':attempt:3:result', '{}', receipt))
                self.assertEqual(self.s._run_job(self.row(ident)), 'blocked')
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM life_scheduler_recoveries').fetchone()[0], 0)

    def test_provider_and_unsafe_jobs_keep_explicit_review(self):
        for kind, detail in [('world', {'detail': 'local life CLI calls are blocked pending operator review'}),
                             ('decision', {'detail': 'CLI HTTP 402'}), ('sleep', {'detail': 'sleep continuity'})]:
            with self.subTest(kind=kind):
                ident = self.blocked(kind, detail)
                self.assertEqual(self.s._run_job(self.row(ident)), 'blocked')

    def test_real_failure_attempts_then_original_message_id_recovers(self):
        ident = self.s._job('agent_message', 'message', {'message_id': 'test-message'})
        self.s._execute = Mock(side_effect=TimeoutError('temporary model failure'))
        for count in range(3):
            self.s._run_job(self.row(ident))
            self.clock.advance(15)
        self.assertEqual(self.row(ident)[3:5], ('blocked', 3))
        self.s._run_job(self.row(ident))
        self.clock.advance(60)
        self.assertEqual(self.s._run_job(self.row(ident)), 'queued')
        self.s._execute = Mock(return_value={'agent_status': 'waiting', 'at': self.clock.now().isoformat()})
        self.assertEqual(self.s._run_job(self.row(ident)), 'worked')
        self.assertEqual(self.s._run_job(self.row(ident)), 'worked')
        self.s._execute.assert_called_once()
        with self.p.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM life_scheduler_attempts').fetchone()[0], 4)
            self.assertEqual(db.execute('SELECT count(*) FROM life_scheduler_recoveries').fetchone()[0], 1)

    def test_natural_wake_is_not_held_by_failed_model_job(self):
        with self.s.worker():
            ident = self.blocked('sync')
            now = self.clock.now()
            with self.p.store.connect() as db:
                state = self.p.store.read(db)
                episode = {'id': 'test-sleep', 'started_at': now.isoformat(), 'settled_until': now.isoformat(),
                           'natural_wake_at': (now + timedelta(seconds=60)).isoformat(), 'seconds': 0}
                state['sleep'].update(status='sleeping', current='test-sleep', episodes=[episode])
                db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
            with patch.object(self.s, '_execute', wraps=self.s._execute) as execute:
                self.clock.advance(30)
                self.assertEqual(self.s.pump(), 'idle_sleep')
                self.clock.advance(30)
                self.assertEqual(self.s.pump(), 'worked')
                self.assertEqual([c.args[0] for c in execute.call_args_list], ['sleep'])
            self.assertEqual(self.p.snapshot()['sleep']['status'], 'awake')
            self.assertEqual(self.p.snapshot()['sleep']['total_seconds'], 60)
            self.assertEqual(self.row(ident)[3], 'blocked')

    def test_restart_preserves_explicit_sleep_without_crediting_gap(self):
        with self.s.worker():
            now = self.clock.now()
            with self.p.store.connect() as db:
                state = self.p.store.read(db)
                episode = {'id': 'restart-sleep', 'started_at': now.isoformat(),
                           'settled_until': now.isoformat(),
                           'natural_wake_at': (now + timedelta(hours=2)).isoformat(),
                           'seconds': 0, 'ended_at': None, 'wake_reason': None}
                state['sleep'].update(status='sleeping', current=episode['id'],
                                      episodes=[episode], awaiting_goodnight=False)
                db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        self.clock.advance(300)
        restarted = Scheduler(self.s.chat, self.s.config)
        with restarted.worker():
            state = self.p.snapshot()
            self.assertEqual(state['sleep']['status'], 'sleeping')
            self.assertEqual(state['sleep']['episodes'][0]['seconds'], 0)
            self.assertEqual(state['sleep']['episodes'][0]['settled_until'], self.clock.now().isoformat())

    def test_stale_checkpoint_cannot_run_against_a_different_activity(self):
        before = self.p.snapshot()
        result = self.s._execute('read', {'checkpoint_basis': {'id': 'old', 'revision': 1, 'progress': 0}}, 'retry')
        self.assertTrue(result['checkpoint_superseded'])
        self.assertEqual(self.p.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
