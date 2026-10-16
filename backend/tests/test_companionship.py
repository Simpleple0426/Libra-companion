import unittest

import test_future_appointments as fixture
from life_prototype.config import canonical
from life_prototype.coarse_plan_updates import enqueue
from life_prototype.companionship import current, revise, reconcile, manual_end
from life_prototype.coarse_plan_execution import requirement, validate_wait
from life_prototype.coarse_plan import DailyAgenda


class CompanionshipTests(unittest.TestCase):
    setUp = fixture.FutureAppointmentTests.setUp

    def send(self, ident, content, action='start', **fields):
        with self.p.store.connect() as db:
            db.execute('INSERT INTO life_received_messages VALUES(?,?,?)',
                       (ident, canonical({'content': content, 'received_at': self.clock.now().isoformat()}), '{}'))
            enqueue(db, ident)
        session = current(self.p.snapshot(), self.clock.now())
        args = dict(message_id=ident, expected_revision=self.p.snapshot()['revision'], action=action,
                    session_id=session['id'] if session else None, title=None, start_at=None,
                    end_at=None, outdoor=None, evidence_quote=content)
        args.update(fields)
        return revise(self.cog, args)

    def test_invitation_report_generic_and_silence_across_days(self):
        start_place = self.p.snapshot()['place']
        self.send('start', '现在陪我逛漫展吧', title='陪用户逛漫展')
        self.assertEqual(requirement(self.cog)['reason'], 'companion_active')
        validate_wait(self.cog)
        self.send('leave', '出发啦', 'update', title='陪用户出行', outdoor=True)
        self.send('arrive', '到漫展了', 'update', title='陪用户逛漫展')
        self.clock.advance(2 * 86400)
        self.cog.agenda = DailyAgenda(self.cog)
        self.cog.agenda.ensure()
        self.assertEqual(current(self.p.snapshot(), self.clock.now())['title'], '陪用户逛漫展')
        self.send('done', '逛完了，还没想好接下来干嘛', 'update', title='陪伴用户')
        self.assertEqual(requirement(self.cog)['title'], '陪伴用户')
        self.assertEqual(self.p.snapshot()['place'], start_place)
        self.assertEqual(self.cog.agenda.view()['current_item']['title'], '陪伴用户')
        self.assertEqual(self.cog.agenda.view()['next_item'], None)

    def test_report_alone_cannot_enter(self):
        with self.assertRaisesRegex(ValueError, 'explicit invitation'):
            self.send('report', '我准备去漫展', title='陪用户逛漫展')
        self.assertIsNone(current(self.p.snapshot(), self.clock.now()))

    def test_future_start_and_explicit_end_survive_restart(self):
        result = self.send('future', '明天7点陪我出发，9点结束', title='陪用户出行',
                           start_at='2026-09-29T07:00:00+08:00', end_at='2026-09-29T09:00:00+08:00')
        self.assertIsNone(current(self.p.snapshot(), self.clock.now()))
        self.clock.advance(27 * 3600)
        reconcile(self.cog)
        self.assertEqual(current(self.p.snapshot(), self.clock.now())['id'], result['companion']['id'])
        self.cog.agenda = DailyAgenda(self.cog)
        self.clock.advance(2 * 3600)
        self.cog.agenda.ensure()
        self.assertIsNone(current(self.p.snapshot(), self.clock.now()))
        self.assertNotEqual(requirement(self.cog)['reason'], 'companion_active')

    def test_strict_end_and_manual_idempotency(self):
        started = self.send('start', '现在陪着我吧')['companion']
        with self.assertRaisesRegex(ValueError, 'unambiguous explicit end'):
            self.send('vague', '你先忙', 'end')
        self.assertIsNotNone(current(self.p.snapshot(), self.clock.now()))
        self.assertEqual(manual_end(self.cog, started['id']), manual_end(self.cog, started['id']))
        self.assertIsNone(current(self.p.snapshot(), self.clock.now()))

    def test_home_arrival_requires_outdoor_and_unambiguous_report(self):
        self.send('start', '现在陪我在家看电影', title='陪用户看电影')
        with self.assertRaisesRegex(ValueError, 'outdoor'):
            self.send('home', '到家了', 'arrive_home')

    def test_restored_session_can_end_again_with_legacy_receipt(self):
        started = self.send('start', '现在陪着我吧')['companion']
        manual_end(self.cog, started['id'])
        with self.p.store.connect() as db:
            # Reproduce a pre-fix manual end followed by an explicit restore.
            state = self.p.snapshot()
            session = state['companionships'][0]
            session.update(status='active', version=session['version'] + 1)
            session.pop('ended_at', None)
            session.pop('end_reason', None)
            db.execute("UPDATE life_state SET body=? WHERE name='current' AND id=1", (canonical(state),))
        receipt = manual_end(self.cog, started['id'])
        self.assertEqual(receipt['status'], 'ended')
        self.assertIsNone(current(self.p.snapshot(), self.clock.now()))
        revision = self.p.snapshot()['revision']
        self.assertEqual(manual_end(self.cog, started['id']), receipt)
        self.assertEqual(self.p.snapshot()['revision'], revision)

    def test_outdoor_home_arrival_ends(self):
        self.send('start', '现在陪我逛漫展')
        self.send('leave', '我出发了', 'update', title='陪用户出行', outdoor=True)
        self.send('home', '我到家啦', 'arrive_home')
        self.assertIsNone(current(self.p.snapshot(), self.clock.now()))

    def test_explicit_release(self):
        self.send('start', '现在陪我逛漫展')
        self.send('end', '不用继续陪我了', 'end')
        self.assertIsNone(current(self.p.snapshot(), self.clock.now()))

    def test_old_button_does_not_end_new_session(self):
        first = self.send('start', '现在陪我逛漫展')['companion']
        manual_end(self.cog, first['id'])
        second = self.send('next', '现在陪我吃饭吧')['companion']
        manual_end(self.cog, first['id'])
        self.assertEqual(current(self.p.snapshot(), self.clock.now())['id'], second['id'])

    def test_home_report_with_continuation_does_not_end(self):
        self.send('start', '现在陪我出门吧', outdoor=True)
        with self.assertRaisesRegex(ValueError, 'unambiguous completed'):
            self.send('home', '到家了，继续陪我看电影', 'arrive_home')
        self.assertIsNotNone(current(self.p.snapshot(), self.clock.now()))

    def test_latest_explicit_end_and_no_duplicate_receipt(self):
        self.send('start', '现在陪我到晚上8点', end_at='2026-09-28T20:00:00+08:00')
        result = self.send('extend', '陪我到晚上9点吧', 'update', end_at='2026-09-28T21:00:00+08:00')
        state = self.p.snapshot()
        self.assertEqual(revise(self.cog, result['companion_proposal']), result)
        self.assertEqual(self.p.snapshot(), state)
        self.clock.advance(16 * 3600)
        reconcile(self.cog)
        self.assertIsNotNone(current(self.p.snapshot(), self.clock.now()))
        self.clock.advance(3600)
        reconcile(self.cog)
        self.assertIsNone(current(self.p.snapshot(), self.clock.now()))

    def test_sleep_is_not_an_end_signal(self):
        self.send('start', '现在陪我待着吧')
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['sleep']['status'] = 'sleeping'
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        self.clock.advance(86400)
        reconcile(self.cog)
        self.assertIsNotNone(current(self.p.snapshot(), self.clock.now()))

    def test_end_replans_only_remaining_day(self):
        session = self.send('start', '现在陪我逛漫展')['companion']
        self.clock.advance(14 * 3600)
        manual_end(self.cog, session['id'])
        body = self.cog.agenda.ensure()
        from life_prototype.clock import utc
        self.assertTrue(all(utc(i['start_at']) >= self.clock.now() for i in body['items']))


if __name__ == '__main__':
    unittest.main()
