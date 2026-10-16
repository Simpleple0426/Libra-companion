from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from life_prototype.activity_engine import Prototype
from life_prototype.clock import TestClock
from life_prototype.cognition import Cognition
from life_prototype.config import canonical
from life_prototype.local_configuration import configurations
from life_prototype.coarse_plan import DailyAgenda
from life_prototype.coarse_plan_updates import enqueue, process_pending, latest


class FutureAppointmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        world, config, sleep, _ = configurations()
        self.clock = TestClock('2026-09-28T04:00:00+08:00')
        self.p = Prototype('future', world, self.clock, root=Path(self.temp.name))
        self.cog = Cognition(self.p, Mock(kind='fixture', provider='test'), config)
        from life_prototype.interaction import Interaction
        self.chat = Interaction(self.cog, sleep)
        self.agenda = self.cog.agenda
        self.agenda.ensure()

    def request(self, ident, appointments=(), cancellations=(), received_at=None):
        content = '明天晚上八点陪我聊天，或按要求取消改期'
        message = {'content': content, 'received_at': received_at or self.clock.now().isoformat()}
        with self.p.store.connect() as db:
            db.execute('INSERT INTO life_received_messages VALUES(?,?,?)',
                       (ident, canonical(message), canonical({'occurred_at': message['received_at']})))
            enqueue(db, ident)
        proposal = {'decision': 'revise', 'reason': '按明确时间安排', 'evidence_quote': content,
                    'cancel_item_ids': [], 'cancel_appointment_ids': list(cancellations), 'appointments': list(appointments)}
        process_pending(self.agenda, proposal=proposal, message_id=ident, expected_revision=self.agenda.read()['revision'])
        return latest(self.agenda)

    def test_old_interrupted_cooking_does_not_block_goodnight(self):
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['activities']['old-breakfast'] = {
                'id': 'old-breakfast', 'kind': 'cooking', 'status': 'interrupted',
            }
            db.execute("UPDATE life_state SET body=? WHERE name='current' AND id=1",
                       (canonical(state),))
        receipt = self.chat.receive(
            'goodnight-after-old-cooking', '晚安', intent='goodnight',
            source='local_app_message', expected_revision=self.p.snapshot()['revision'],
        )
        self.assertNotEqual(receipt['sleep_request'], 'blocked_safe_shutdown_unconfigured')
        self.assertEqual(receipt['sleep']['status'], 'sleeping')

    def test_quiet_night_fallback_starts_once_without_message(self):
        self.assertIsNone(self.chat.start_fallback_sleep_if_ready())
        self.clock.advance(22 * 3600)
        result = self.chat.start_fallback_sleep_if_ready()
        self.assertEqual(result['sleep_request'], 'quiet_night_fallback')
        episode = result['sleep']['episodes'][-1]
        self.assertIsNone(episode['start_message_id'])
        self.assertIsNotNone(episode['natural_wake_at'])
        self.assertIsNone(self.chat.start_fallback_sleep_if_ready())
        self.assertEqual(len(self.p.snapshot()['sleep']['episodes']), 1)

    def test_quiet_night_fallback_waits_for_recent_contact(self):
        self.clock.advance(22 * 3600)
        self.chat.receive('late-chat', '还在聊天', source='local_app_message')
        self.assertIsNone(self.chat.start_fallback_sleep_if_ready())
        self.clock.advance(30 * 60)
        self.assertIsNotNone(self.chat.start_fallback_sleep_if_ready())

    def test_quiet_night_fallback_does_not_interrupt_activity(self):
        self.clock.advance(22 * 3600)
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['active'] = 'ongoing'
            db.execute("UPDATE life_state SET body=? WHERE name='current' AND id=1",
                       (canonical(state),))
        self.assertIsNone(self.chat.start_fallback_sleep_if_ready())

    def test_fallback_window_and_notice_before_sleep(self):
        self.clock.advance(21 * 3600)
        notice = Mock(side_effect=lambda night: self.assertEqual(
            self.p.snapshot()['sleep']['status'], 'awake'))
        self.chat.before_fallback_sleep = notice
        self.assertIsNone(self.chat.start_fallback_sleep_if_ready())
        notice.assert_not_called()
        self.clock.advance(3600)
        self.assertIsNotNone(self.chat.start_fallback_sleep_if_ready())
        notice.assert_called_once_with('2026-09-29')
        self.chat.start_fallback_sleep_if_ready()
        notice.assert_called_once()

    def test_failed_notice_keeps_fallback_awake_for_retry(self):
        self.clock.advance(22 * 3600)
        self.chat.before_fallback_sleep = Mock(side_effect=RuntimeError('delivery failed'))
        with self.assertRaises(RuntimeError):
            self.chat.start_fallback_sleep_if_ready()
        self.assertEqual(self.p.snapshot()['sleep']['status'], 'awake')

    def test_fallback_does_not_start_at_four(self):
        self.clock.advance(24 * 3600)
        self.assertIsNone(self.chat.start_fallback_sleep_if_ready())

    def test_running_cooking_does_not_block_goodnight(self):
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['activities']['active-cooking'] = {
                'id': 'active-cooking', 'kind': 'cooking', 'status': 'running',
                'target': 'breakfast', 'place': state['place'], 'progress': 0,
                'revision': 1, 'started_at': self.clock.now().isoformat(),
                'last_progress_at': self.clock.now().isoformat(),
                'next_due_at': None, 'ingredients_consumed': False,
            }
            state['active'] = 'active-cooking'
            db.execute("UPDATE life_state SET body=? WHERE name='current' AND id=1",
                       (canonical(state),))
        receipt = self.chat.receive(
            'goodnight-during-cooking', '晚安', intent='goodnight',
            source='local_app_message', expected_revision=self.p.snapshot()['revision'],
        )
        self.assertNotEqual(receipt['sleep_request'], 'blocked_safe_shutdown_unconfigured')
        self.assertEqual(receipt['sleep']['status'], 'sleeping')

    def test_pending_evening_shower_defers_sleep_until_completed(self):
        self.clock.advance(19 * 3600)
        from life_prototype.daily_obligations import unresolved_before_sleep
        state = self.p.snapshot()
        self.assertTrue(unresolved_before_sleep(self.p.config, state, self.clock.now()))

        receipt = self.chat.receive(
            'goodnight-with-pending-shower', '晚安', intent='goodnight',
            source='local_app_message', expected_revision=state['revision'],
        )

        self.assertEqual(receipt['sleep_request'], 'accepted_pending_bedtime_routine')
        self.assertEqual(receipt['sleep']['status'], 'awake')
        self.assertEqual(receipt['sleep']['pending_goodnight']['message_id'],
                         'goodnight-with-pending-shower')

        with self.p.store.connect() as db:
            current = self.p.store.read(db)
            current['activities']['finished-shower'] = {
                'id': 'finished-shower', 'kind': 'showering',
                'target': 'routine:2026-09-28:shower', 'status': 'completed',
            }
            db.execute("UPDATE life_state SET body=? WHERE name='current' AND id=1",
                       (canonical(current),))

        started = self.chat.start_pending_sleep_if_ready()
        self.assertIsNotNone(started)
        self.assertEqual(started['sleep']['status'], 'sleeping')
        self.assertEqual(started['sleep']['episodes'][-1]['start_message_id'],
                         'goodnight-with-pending-shower')

    def test_goodnight_does_not_interrupt_shower_before_deferred_sleep(self):
        self.clock.advance(19 * 3600)
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['activities']['evening-shower'] = {
                'id': 'evening-shower', 'kind': 'showering',
                'target': 'routine:2026-09-28:shower', 'status': 'running',
                'place': 'home.f2.bathroom', 'progress': 0, 'revision': 1,
                'started_at': self.clock.now().isoformat(),
                'last_progress_at': self.clock.now().isoformat(),
                'next_due_at': None,
            }
            state['active'] = 'evening-shower'
            db.execute("UPDATE life_state SET body=? WHERE name='current' AND id=1",
                       (canonical(state),))

        receipt = self.chat.receive(
            'goodnight-during-shower', '晚安', intent='goodnight',
            source='local_app_message', expected_revision=state['revision'],
        )

        self.assertEqual(receipt['sleep_request'], 'accepted_pending_bedtime_routine')
        self.assertEqual(receipt['active'], 'evening-shower')
        self.assertEqual(self.p.snapshot()['activities']['evening-shower']['status'], 'running')

    def test_latest_goodnight_blocked_by_retired_rule_is_repaired_once(self):
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['activities']['old-breakfast'] = {
                'id': 'old-breakfast', 'kind': 'cooking', 'status': 'interrupted',
            }
            db.execute("UPDATE life_state SET body=? WHERE name='current' AND id=1",
                       (canonical(state),))
            request = {'content': '晚安', 'intent': 'goodnight', 'interrupt': False,
                       'commitment': None, 'expected_revision': state['revision'],
                       'source': 'local_app_message'}
            db.execute('INSERT INTO life_received_messages VALUES(?,?,?)',
                       ('blocked-goodnight', canonical(request), canonical({
                           'sleep_request': 'blocked_safe_shutdown_unconfigured'})))
        repaired = self.chat.repair_stale_goodnight()
        self.assertEqual(repaired['sleep']['status'], 'sleeping')
        revision = self.p.snapshot()['revision']
        self.assertIsNone(self.chat.repair_stale_goodnight())
        self.assertEqual(self.p.snapshot()['revision'], revision)

    def test_explicit_wake_time_overrides_rest_day_default(self):
        self.clock.advance(21 * 3600)
        self.cog.calendar_provider = lambda day: {
            'date': day, 'day_type': 'rest_day', 'calendar_recorded': True,
        }
        with self.p.store.connect() as db:
            db.execute('INSERT INTO life_received_messages VALUES(?,?,?)', (
                'wake-promise', canonical({'content': '我们七点起床，七点半出发'}), '{}'))
        receipt = self.chat.receive(
            'night', '晚安', intent='goodnight', source='local_app_message',
            expected_revision=self.p.snapshot()['revision'])
        self.assertEqual(receipt['sleep']['episodes'][-1]['branch'], 'explicit_user_wake')
        self.assertTrue(receipt['sleep']['episodes'][-1]['natural_wake_at'].endswith('23:00:00+00:00'))

    def appointment(self, at='2026-09-29T20:00:00+08:00', duration=1800):
        return {'title': '陪用户聊天', 'start_at': at, 'duration_seconds': duration, 'place_id': 'home.f1.living'}

    def test_future_intention_survives_restart_and_materializes_on_date(self):
        before = self.p.snapshot()
        old = self.agenda.read()
        result = self.request('tomorrow', [self.appointment()])
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(self.agenda.read(), old)
        self.assertEqual(self.p.snapshot(), before)
        self.agenda = self.cog.agenda = DailyAgenda(self.cog)
        future = self.agenda.view()['upcoming_appointments']
        self.assertEqual(len(future), 1)
        self.clock.advance(86400)
        body = self.agenda.ensure()
        self.assertFalse(body.get('conflicts'), body.get('conflicts'))
        self.assertTrue(any(i.get('appointment_id') == future[0]['id'] for i in body['items']))
        self.assertEqual(self.p.snapshot(), before)

    def test_cancel_future_does_not_resurrect_after_restart(self):
        self.request('new', [self.appointment()])
        ident = self.agenda.view()['upcoming_appointments'][0]['id']
        result = self.request('cancel', cancellations=[ident])
        self.assertEqual(result['status'], 'applied', result)
        self.agenda = self.cog.agenda = DailyAgenda(self.cog)
        self.clock.advance(86400)
        body = self.agenda.ensure()
        self.assertFalse(any(i.get('appointment_id') == ident for i in body['items']))
        self.assertEqual(self.agenda.view()['upcoming_appointments'], [])

    def test_reschedule_and_conflict_are_atomic(self):
        self.request('first', [self.appointment()])
        ident = self.agenda.view()['upcoming_appointments'][0]['id']
        result = self.request('move', [self.appointment('2026-10-03T20:00:00+08:00')], [ident])
        self.assertEqual(result['status'], 'applied', result)
        before = self.agenda.view()['upcoming_appointments']
        result = self.request('overlap', [self.appointment('2026-10-03T20:10:00+08:00')])
        self.assertNotEqual(result['status'], 'applied')
        self.assertEqual(self.agenda.view()['upcoming_appointments'], before)

    def test_same_day_and_midnight_reservations(self):
        result = self.request('today', [self.appointment('2026-09-28T20:00:00+08:00')])
        self.assertEqual(result['status'], 'applied', result)
        self.assertTrue(any(i.get('appointment_id') for i in self.agenda.read()['items']))
        result = self.request('midnight', [self.appointment('2026-09-29T23:50:00+08:00', 1800)])
        self.assertEqual(result['status'], 'applied', result)

    def test_past_or_stale_immediate_request_is_not_shifted_to_now(self):
        for ident, appointment in [('past', self.appointment('2026-09-27T20:00:00+08:00')),
                                    ('immediate', self.appointment(None))]:
            with self.subTest(ident=ident):
                result = self.request(ident, [appointment], received_at='2026-09-27T12:00:00+08:00')
                self.assertNotEqual(result['status'], 'applied')
                with self.p.store.connect() as db:
                    db.execute("UPDATE life_agenda_messages SET status='needs_review' WHERE message_id=?", (ident,))
        self.assertEqual(self.agenda.view()['upcoming_appointments'], [])

    def test_invalid_future_preview_does_not_cancel_existing_reservation(self):
        self.request('first', [self.appointment()])
        before = self.agenda.view()['upcoming_appointments']
        result = self.request('invalid', [self.appointment('2026-09-30T03:50:00+08:00')], [before[0]['id']])
        self.assertNotEqual(result['status'], 'applied')
        self.assertEqual(self.agenda.view()['upcoming_appointments'], before)

    def test_future_change_publishes_plan_trigger_only_once(self):
        from life_prototype.activity_feed import read
        self.request('future-trigger', [self.appointment()])
        self.assertFalse(process_pending(self.agenda, message_id='future-trigger'))
        with self.p.store.connect() as db:
            items = read(db, self.p.store.read(db), self.p.config, limit=None)
        self.assertEqual([(i['id'], i['kind']) for i in items], [('agenda-review:future-trigger', 'agenda_changed')])

    def test_old_same_day_appointment_is_adopted_once(self):
        self.request('legacy', [self.appointment('2026-09-28T20:00:00+08:00')])
        with self.p.store.connect() as db:
            db.execute('DELETE FROM life_appointments')
        self.agenda = self.cog.agenda = DailyAgenda(self.cog)
        items = self.agenda.view()['upcoming_appointments']
        self.assertEqual(len(items), 1)
        self.request('cancel-legacy', cancellations=[items[0]['id']])
        self.agenda = self.cog.agenda = DailyAgenda(self.cog)
        self.assertEqual(self.agenda.view()['upcoming_appointments'], [])


if __name__ == '__main__':
    unittest.main()
