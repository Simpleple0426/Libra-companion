import unittest
from pathlib import Path
import test_future_appointments as fixture
from life_prototype.config import canonical
from life_prototype.coarse_plan_execution import requirement, enter_current
from life_prototype.coarse_locations import advance
from life_prototype import skill_home_activity, skill_personal_care


class MorningWakeTests(unittest.TestCase):
    setUp = fixture.FutureAppointmentTests.setUp

    def test_four_am_rollover_does_not_start_morning_or_publish_place(self):
        before = self.p.snapshot()
        self.assertEqual(self.agenda.read()['items'][0]['activity'], 'await_morning')
        self.assertEqual(requirement(self.cog)['reason'], 'await_confirmed_morning_wake')
        self.assertFalse(advance(self.cog))
        self.assertFalse(enter_current(self.cog))
        self.assertEqual(self.p.snapshot(), before)
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind IN ('woke','care_start','at_place')").fetchone()[0], 0)

    def test_confirmed_wake_replans_before_care_and_emits_once(self):
        # A sleeping test episode; tick owns both wake state and its event.
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['sleep'].update(status='sleeping', current='night', episodes=[{
                'id':'night', 'started_at':self.clock.now().isoformat(),
                'settled_until':self.clock.now().isoformat(), 'seconds':0,
                'natural_wake_at':'2026-09-28T07:00:00+08:00'}])
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        self.clock.advance(3 * 3600)
        self.chat.tick('morning')
        self.chat.tick('morning-again')
        self.agenda.ensure()
        self.assertEqual(self.agenda.read()['items'][0]['intent'], '起床及晨间准备')
        self.cog.resource_root = Path(__file__).resolve().parents[2]
        advance(self.cog)
        skill_home_activity.prepare(self.cog)
        advance(self.cog)
        plan = skill_personal_care.prepare(self.cog)['care']
        state = self.p.snapshot()
        self.p.command('wash', state['revision'], 'start', activity_id='wash', kind=plan['kind'], target=plan['id'])
        with self.p.store.connect() as db:
            rows = db.execute("SELECT kind,description,occurred_at FROM events WHERE kind IN ('woke','care_start') ORDER BY rowid").fetchall()
        self.assertEqual([row[0] for row in rows], ['woke', 'care_start'])
        self.assertEqual(rows[0][1], '左然起床了')
        self.assertEqual(rows[0][2], '2026-09-27T23:00:00+00:00')

    def test_previous_day_wake_does_not_authorize_new_day_wash(self):
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['sleep']['last_wake'] = {'at':'2026-09-27T07:00:00+08:00'}
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        self.clock.advance(3 * 3600)
        self.agenda.ensure()
        self.assertEqual(requirement(self.cog)['reason'], 'await_confirmed_morning_wake')
