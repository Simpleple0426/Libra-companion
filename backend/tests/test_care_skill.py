from copy import deepcopy
from datetime import timedelta
import json
import unittest
import test_meal_skill as fixture
from life_prototype import skill_personal_care as care_skill
from life_prototype.coarse_plan_execution import requirement
from life_prototype.coarse_plan_schema import detail_kinds, pack_item, unpack_item
from life_prototype.state_view import progress_view


class CareTests(unittest.TestCase):
    setUp=fixture.MealSkillTests.setUp
    command=fixture.MealSkillTests.command

    def setup_care(self,routine='morning_wash',place='home.f2.bathroom'):
        if routine in {'shower','bedtime_wash','bedtime_preparation'}: self.clock.advance(8*3600)
        self.item.update(state_type='free',kind='free',activity=routine,place=place,
                         reference_id='routine:2026-09-28:shower' if routine=='shower' else None,
                         start_at=self.clock.now().isoformat(),end_at=(self.clock.now()+timedelta(hours=1)).isoformat())
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['place']=place
            if routine == 'morning_wash':
                state['sleep']['last_wake'] = {'at': self.clock.now().isoformat()}
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(json.dumps(state),))
        return care_skill.prepare(self.cog)['care']

    def ticks(self,seconds):
        while seconds>0:
            part=min(seconds,60);self.clock.advance(part);care_skill.heartbeat(self.cog);seconds-=part

    def start(self,plan):
        self.command('care-start','start',activity_id='care',kind=plan['kind'],target=plan['id'])

    def test_wash_steps_advance_complete_once_and_observation_is_verified(self):
        plan=self.setup_care();self.start(plan)
        self.assertIn('刷牙',self.p.snapshot()['activities']['care']['description'])
        self.ticks(120)
        self.assertIn('洗脸',self.p.snapshot()['activities']['care']['description'])
        self.ticks(plan['duration_seconds']-120)
        self.assertEqual(self.p.snapshot()['activities']['care']['status'],'completed')
        self.assertEqual(requirement(self.cog)['mode'],'hold')
        self.cog.ingest();self.cog.ingest()
        from life_prototype.event_assimilation import control_event_evidence
        with self.p.store.connect() as db:
            rows=[json.loads(r[0]) for r in db.execute('SELECT body FROM life_observations')]
            obs=next(r for r in rows if r['type']=='care_completed')
            control_event_evidence(self.p,db,obs)
            bad=deepcopy(obs);bad['fact']['actual_result']['seconds']=99999
            with self.assertRaises(ValueError): control_event_evidence(self.p,db,bad)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='care_completed'").fetchone()[0],1)
        self.assertEqual(self.model.calls,[])

    def test_bedtime_preparation_remains_awake(self):
        plan=self.setup_care('bedtime_preparation','home.f2.bedroom');self.start(plan)
        self.ticks(plan['duration_seconds'])
        state=self.p.snapshot()
        self.assertEqual(state['sleep']['status'],'awake')
        self.assertIn('等待晚安',state['activities']['care']['description'])
        self.assertEqual(requirement(self.cog)['reason'],'care_completed_wait_awake')
        self.item.update(id='later-wait',activity='await_goodnight')
        self.assertEqual(requirement(self.cog)['reason'],'care_completed_wait_awake')

    def test_pause_preserves_progress_but_restart_closes_old_activity(self):
        plan=self.setup_care();self.start(plan);self.ticks(60)
        self.command('pause','interrupt',activity_id='care',reason='message')
        self.clock.advance(300)
        self.command('resume','resume',activity_id='care');self.ticks(60)
        self.clock.advance(300)
        self.command('recovery','recover',reason='restart')
        self.assertEqual(self.p.snapshot()['activities']['care']['progress'],120)
        self.assertEqual(self.p.snapshot()['care_plans'][plan['id']]['progress'],120)
        self.assertEqual(self.p.snapshot()['activities']['care']['status'],'failed')
        self.assertIsNone(self.p.snapshot()['active'])
        with self.assertRaisesRegex(ValueError,'cannot resume'):
            self.command('resume2','resume',activity_id='care')
        self.ticks(120)
        self.assertEqual(self.p.snapshot()['care_plans'][plan['id']]['progress'],120)
        self.assertNotIn('completed_at',self.p.snapshot()['care_plans'][plan['id']])

    def test_deadline_does_not_fake_completion(self):
        plan=self.setup_care();self.start(plan)
        self.ticks(60);self.command('pause','interrupt',activity_id='care',reason='message')
        self.clock.advance(3510)
        self.command('resume','resume',activity_id='care');self.ticks(60)
        state=self.p.snapshot()
        self.assertEqual(state['activities']['care']['progress'],90)
        self.assertNotIn('completed_at',state['care_plans'][plan['id']])

    def test_evening_shower_satisfies_daily_obligation(self):
        plan=self.setup_care('shower');self.start(plan);self.ticks(plan['duration_seconds'])
        from life_prototype.daily_obligations import status
        obligations=status(self.p.config,self.p.snapshot(),self.clock.now(),self.cog.calendar_provider)
        shower=next(r for r in obligations if r['kind']=='shower')
        self.assertEqual(shower['status'],'completed')

    def test_morning_shower_and_wrong_room_rejected(self):
        self.item.update(state_type='free',activity='shower',place='home.f2.bathroom')
        with self.assertRaises(ValueError): care_skill.prepare(self.cog)
        self.item.update(activity='bedtime_preparation',place='home.f2.bathroom')
        with self.assertRaises(ValueError): care_skill.prepare(self.cog)

    def test_old_shower_records_are_not_replaced_or_repeated(self):
        self.clock.advance(8*3600)
        self.item.update(state_type='free',activity='shower',place='home.f2.bathroom',
            reference_id='routine:2026-09-28:shower',start_at=self.clock.now().isoformat(),
            end_at=(self.clock.now()+timedelta(hours=1)).isoformat())
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['place']=self.item['place']
            state['activities']['legacy']={'id':'legacy','kind':'showering','target':self.item['reference_id'],'status':'interrupted'}
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(json.dumps(state),))
        self.assertEqual(requirement(self.cog)['reason'],'finish_existing_shower')
        state=self.p.snapshot();state['activities']['legacy']['status']='completed'
        self.assertEqual(requirement(self.cog,state)['mode'],'hold')

    def test_packed_coarse_intent_routes_care_instead_of_reading(self):
        parent={'id':'wash','kind':'free','state_type':'free','activity':'morning_wash',
                'place':'home.f2.bathroom','place_name':'卫生间',
                'start_at':self.clock.now().isoformat(),'end_at':(self.clock.now()+timedelta(minutes=10)).isoformat()}
        parent=unpack_item(pack_item(parent))
        self.assertEqual(care_skill.routine(parent),'morning_wash')
        self.assertEqual(detail_kinds(parent),set())

    def test_tool_action_and_status_support_new_activity_kind(self):
        plan=self.setup_care()
        from life_prototype.scheduler import Scheduler,DEFAULTS
        from life_prototype.autonomous_agent import LifeAgent
        agent=LifeAgent(Scheduler(self.chat,DEFAULTS))
        result=agent._action('care-action',{'expected_revision':self.p.snapshot()['revision'],
            'action':{'operation':'start','activity_id':None,'kind':'personal_care','target':plan['id']},'movement_purpose':None})
        active=self.p.snapshot()['activities'][result['active_activity']]
        self.assertEqual(progress_view(active,self.p.config)['progress_unit'],'simulated_care_seconds')
        from life_prototype.home_world import evaluate
        with self.assertRaises(ValueError): evaluate(self.p,self.p.snapshot(),self.clock.now())


if __name__=='__main__': unittest.main()
