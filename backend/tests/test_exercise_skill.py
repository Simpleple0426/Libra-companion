from datetime import timedelta
import json
import unittest
import test_meal_skill as fixture
from life_prototype import skill_exercise as skill
from life_prototype.coarse_plan_execution import requirement, pause_mismatch


class ExerciseTests(unittest.TestCase):
    setUp=fixture.MealSkillTests.setUp
    command=fixture.MealSkillTests.command

    def setup_exercise(self, gym=False):
        place='test.gym' if gym else 'home.f1.living'
        if gym:
            self.p.config['places'][place]={'name':'OneMore健身房','parent':None,'status':'confirmed','source':'fixture'}
            self.p.config['household_world']['edges'].append([place,'firm.office'])
        self.item.update(id='exercise',state_type='exercising',kind='exercise',activity='exercising',place=place,
                         end_at=(self.clock.now()+timedelta(minutes=5)).isoformat())
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['place']=place
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(json.dumps(state),))
        plan=skill.prepare(self.cog)['exercise']
        self.command('start-exercise','start',activity_id='exercise',kind='exercising',target=plan['id'])
        return plan

    def ticks(self,seconds):
        while seconds:
            part=min(60,seconds);self.clock.advance(part);skill.heartbeat(self.cog);seconds-=part

    def sport(self, kind):
        from life_prototype.meal_places import configured
        self.p.config=configured(self.p.config,{'locations':{kind:['蓝湖游泳馆' if kind=='swimming' else '射击馆']}})
        place=next(key for key,value in self.p.config['places'].items() if value.get('exercise_mode')==kind)
        from life_prototype.home_world import path
        self.assertTrue(path(self.p.config,'home.f1.living',place))
        self.assertEqual(configured(self.p.config,{'locations':{kind:[self.p.config['places'][place]['name']]}}),self.p.config)
        self.item.update(id=kind,state_type='exercising',activity=kind,place=place,
                         end_at=(self.clock.now()+timedelta(minutes=5)).isoformat())
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['place']=place
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(json.dumps(state),))
        plan=skill.prepare(self.cog)['exercise']
        self.command('sport','start',activity_id='sport',kind='exercising',target=plan['id'])
        return plan

    def test_swimming_boundary_events_once(self):
        plan=self.sport('swimming');self.ticks(240);self.clock.advance(60)
        pause_mismatch(self.cog);skill.heartbeat(self.cog)
        self.assertEqual(self.p.snapshot()['exercise_checkins'][plan['id']]['active_seconds'],300)
        self.cog.ingest();self.cog.ingest()
        with self.p.store.connect() as db:
            self.assertEqual([r[0] for r in db.execute("SELECT description FROM events WHERE kind LIKE 'exercise_%' ORDER BY rowid")],
                             ['左然开始游泳','左然结束游泳'])
        self.assertEqual(self.model.calls,[])

    def test_shooting_early_departure_events(self):
        plan=self.sport('shooting');self.ticks(60)
        from life_prototype.state_view import progress_view
        self.assertEqual(progress_view(self.p.snapshot()['activities']['sport'],self.p.config)['target_name'],'射击')
        self.command('pause-sport','interrupt',activity_id='sport',reason='提前离开')
        from coarse_location_fixture import depart
        depart(self, 'firm.office')
        self.assertEqual(self.p.snapshot()['exercise_checkins'][plan['id']]['active_seconds'],60)
        with self.p.store.connect() as db:
            self.assertEqual([r[0] for r in db.execute("SELECT description FROM events WHERE kind LIKE 'exercise_%' ORDER BY rowid")],
                             ['左然开始射击','左然结束射击'])

    def test_home_completes_once_with_exact_start_text_and_memory(self):
        plan=self.setup_exercise();self.ticks(300)
        self.assertEqual(self.p.snapshot()['exercise_checkins'][plan['id']]['active_seconds'],300)
        self.assertFalse(skill.heartbeat(self.cog))
        self.cog.ingest();self.cog.ingest()
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT description FROM events WHERE kind='exercise_start'").fetchone()[0],'左然开始跑步')
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='exercise_completed'").fetchone()[0],1)
        self.assertEqual(self.model.calls,[])

    def test_gym_only_checks_in_on_actual_departure(self):
        plan=self.setup_exercise(True);self.ticks(300)
        self.assertFalse(self.p.snapshot().get('exercise_checkins'))
        from coarse_location_fixture import depart
        depart(self, 'firm.office')
        self.assertEqual(self.p.snapshot()['exercise_checkins'][plan['id']]['active_seconds'],300)
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='exercise_completed'").fetchone()[0],1)
        self.cog.ingest()

    def test_pause_recovery_does_not_backfill_or_double_count(self):
        plan=self.setup_exercise();self.ticks(60)
        self.command('pause','interrupt',activity_id='exercise',reason='chat')
        self.clock.advance(60)
        self.command('resume','resume',activity_id='exercise')
        self.ticks(60)
        self.clock.advance(60)
        self.command('recover','recover',reason='restart')
        self.assertEqual(self.p.snapshot()['exercise_sessions'][plan['id']]['progress'],120)
        self.assertEqual(self.p.snapshot()['activities']['exercise']['status'],'failed')
        self.assertIsNone(self.p.snapshot()['active'])
        with self.assertRaisesRegex(ValueError,'cannot resume'):
            self.command('resume2','resume',activity_id='exercise')
        self.ticks(60)
        self.assertEqual(self.p.snapshot()['exercise_sessions'][plan['id']]['progress'],120)
        self.assertFalse(self.p.snapshot().get('exercise_checkins'))

    def test_coarse_boundary_finishes_home_before_heartbeat(self):
        plan=self.setup_exercise();self.ticks(240);self.clock.advance(60)
        pause_mismatch(self.cog)
        self.assertEqual(self.p.snapshot()['exercise_checkins'][plan['id']]['active_seconds'],300)

    def test_gym_coarse_boundary_waits_for_departure_and_checks_in_once(self):
        plan=self.setup_exercise(True);self.ticks(240);self.clock.advance(60)
        self.assertTrue(pause_mismatch(self.cog))
        self.assertFalse(pause_mismatch(self.cog))
        self.assertFalse(skill.heartbeat(self.cog))
        self.assertFalse(self.p.snapshot().get('exercise_checkins'))
        from coarse_location_fixture import depart
        depart(self, 'firm.office')
        self.assertEqual(self.p.snapshot()['exercise_checkins'][plan['id']]['active_seconds'],300)
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='exercise_completed'").fetchone()[0],1)

    def test_late_boundary_never_counts_unobserved_gap(self):
        plan=self.setup_exercise();self.ticks(60);self.clock.advance(600)
        self.assertTrue(pause_mismatch(self.cog))
        self.assertEqual(self.p.snapshot()['exercise_checkins'][plan['id']]['active_seconds'],60)
        self.assertFalse(skill.heartbeat(self.cog))

    def test_early_plan_replacement_does_not_claim_completion(self):
        self.setup_exercise();self.ticks(60)
        self.item.update(activity='working',state_type='working',place='firm.office')
        self.assertTrue(pause_mismatch(self.cog))
        self.assertEqual(self.p.snapshot()['activities']['exercise']['status'],'failed')
        self.assertFalse(self.p.snapshot().get('exercise_checkins'))

    def test_no_execution_no_checkin_and_unsupported_place_blocked(self):
        self.item.update(state_type='exercising',activity='exercising',place='home.f1.kitchen')
        self.assertEqual(requirement(self.cog)['reason'],'exercise_place_not_supported')
        self.assertFalse(self.p.snapshot().get('exercise_checkins'))

    def test_agent_and_world_guard(self):
        plan=self.setup_exercise();self.ticks(60)
        from life_prototype.home_world import evaluate
        with self.assertRaises(ValueError): evaluate(self.p,self.p.snapshot(),self.clock.now())
        self.command('pause','interrupt',activity_id='exercise',reason='chat')
        from life_prototype.scheduler import Scheduler, DEFAULTS
        from life_prototype.autonomous_agent import LifeAgent
        agent=LifeAgent(Scheduler(self.chat,DEFAULTS))
        agent._action('resume-agent',{'expected_revision':self.p.snapshot()['revision'],
            'action':{'operation':'resume','activity_id':'exercise','kind':'exercising','target':plan['id']},'movement_purpose':None})
        self.assertEqual(self.p.snapshot()['active'],'exercise')


if __name__=='__main__': unittest.main()
