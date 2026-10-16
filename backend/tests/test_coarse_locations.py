import unittest
from copy import deepcopy
import test_future_appointments as fixture
from life_prototype.config import canonical
from life_prototype.coarse_plan_schema import pack
from life_prototype.coarse_locations import advance
from life_prototype.coarse_plan_execution import requirement
from life_prototype.clock import utc


class CoarseLocationTests(unittest.TestCase):
    setUp = fixture.FutureAppointmentTests.setUp

    def plan(self):
        self.clock.advance(10 * 3600)
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['place'] = 'firm.office'
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        body = self.agenda.ensure()
        commute = dict(id='trip',kind='commute',activity='moving',state_type='commuting',
            title='回家',place='firm.office',destination='home.f2.bathroom',
            start_at='2026-09-28T14:00:00+08:00',end_at='2026-09-28T14:30:00+08:00')
        shower = dict(id='shower',kind='shower',activity='shower',state_type='free',intent='洗澡',
            title='洗澡',place='home.f2.bathroom',reference_id='routine:2026-09-28:shower',
            start_at='2026-09-28T14:30:00+08:00',end_at='2026-09-28T15:00:00+08:00')
        body.update(items=[commute,shower],revision=body['revision']+1)
        with self.p.store.connect() as db:
            db.execute('INSERT INTO life_daily_agendas VALUES(?,?,?)',(body['date'],body['revision'],canonical(pack(body))))

    def test_coarse_commute_owns_arrival_no_movement_or_shower_completion(self):
        self.plan()
        self.assertTrue(advance(self.cog))
        self.assertEqual(requirement(self.cog)['reason'],'coarse_commute_in_progress')
        self.assertEqual(self.p.snapshot()['place'],'firm.office')
        self.assertFalse(advance(self.cog))
        self.clock.advance(1800)
        self.assertTrue(advance(self.cog))
        state=self.p.snapshot()
        self.assertEqual(state['place'],'home.f2.bathroom')
        self.assertFalse(state['active'])
        self.assertFalse(any(a['kind'] in {'moving','showering'} for a in state['activities'].values()))
        self.assertFalse(advance(self.cog))
        with self.p.store.connect() as db:
            rows=db.execute("SELECT occurred_at,description FROM events WHERE id LIKE 'coarse-location:%' ORDER BY rowid").fetchall()
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[-1][1],'左然回到了家')
        self.assertEqual(utc(rows[-1][0]),self.clock.now())

    def test_new_movement_is_rejected(self):
        self.plan()
        state=self.p.snapshot()
        with self.assertRaisesRegex(ValueError,'independent movement removed'):
            self.p.command('forbidden',state['revision'],'start',activity_id='move',kind='moving',target='home.f2.bathroom')

    def test_companionship_is_not_relocated(self):
        self.plan()
        with self.p.store.connect() as db:
            state=self.p.store.read(db)
            state['companionships']=[dict(id='c',status='active',start_at=self.clock.now().isoformat(),end_at=None,title='陪伴用户')]
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
        before=self.p.snapshot()
        self.assertFalse(advance(self.cog))
        self.assertEqual(before,self.p.snapshot())
