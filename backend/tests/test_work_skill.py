from datetime import timedelta
from copy import deepcopy
import json
import unittest
import test_meal_skill as fixture
from life_prototype import skill_work as skill, firm_catalog
from life_prototype.clock import utc
from life_prototype.config import canonical,digest
from life_prototype.coarse_plan_execution import requirement,pause_mismatch
from life_prototype.home_world import checkpoint


class WorkTests(unittest.TestCase):
    command=fixture.MealSkillTests.command

    def setUp(self):
        fixture.MealSkillTests.setUp(self)
        self.p.config=firm_catalog.configured(self.p.config)
        self.slot()
        self.set_place('firm.office')

    def slot(self,place='firm.office',minutes=180,ident='morning'):
        self.item.update(id=ident,state_type='working',kind='work',activity='working',intent='工作',
            place=place,reference_id=None,start_at=self.clock.now().isoformat(),
            end_at=(self.clock.now()+timedelta(minutes=minutes)).isoformat())

    def set_place(self,place):
        with self.p.store.connect() as db:
            s=self.p.store.read(db);s['place']=place
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(s),))

    def ticks(self,seconds):
        while seconds>0:
            part=min(60,seconds);self.clock.advance(part);skill.heartbeat(self.cog);seconds-=part

    def move(self,place,ident):
        from life_prototype.coarse_plan_schema import site_id
        from life_prototype.coarse_locations import advance
        if site_id(place) != site_id(self.item['place']):
            from coarse_location_fixture import depart
            depart(self, place, ident)
        else:
            advance(self.cog)

    def start_step(self,step):
        self.move(step['place'],'move:'+step['id'])
        self.command(step['id'],'start',activity_id=step['id'],kind='work',target=step['id'])

    def test_office_phases_break_return_events_memories_no_model(self):
        ident=next('slot'+str(i) for i in range(100) if int(digest('slot'+str(i))[:8],16)%4==0)
        self.slot(ident=ident)
        saved=skill.prepare(self.cog);self.assertEqual(saved,skill.prepare(self.cog))
        steps=saved['steps'];self.assertIn('break',[s['task'] for s in steps])
        with self.p.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],0)
        for step in steps:
            self.start_step(step)
            self.assertEqual(requirement(self.cog)['targets'],[step['id']])
            self.ticks(step['seconds'])
        self.assertEqual(self.p.snapshot()['place'],'firm.office')
        self.assertFalse(self.p.snapshot()['active'])
        self.cog.ingest();self.cog.ingest()
        with self.p.store.connect() as db:
            events=[r[0] for r in db.execute("SELECT description FROM events WHERE kind LIKE 'work_%'")]
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind LIKE 'work_%' AND (coarse_plan_id IS NULL OR fine_plan_id IS NULL)").fetchone()[0],0)
            self.assertTrue(any('继续查阅' in x for x in events))
            self.assertFalse(any('文书' in x or '办结' in x for x in events))
            self.assertEqual(db.execute("SELECT count(*) FROM life_memories WHERE description IN (SELECT description FROM events WHERE kind LIKE 'work_%')").fetchone()[0],len(events))
        self.assertEqual(self.model.calls,[])

    def test_manual_pause_can_resume_but_restart_closes_work_progress(self):
        self.slot(minutes=30);step=skill.prepare(self.cog)['steps'][0];self.start_step(step)
        self.ticks(60);self.command('pause','interrupt',activity_id=step['id'],reason='用户互动')
        self.clock.advance(120);self.command('resume','resume',activity_id=step['id']);self.ticks(60)
        self.clock.advance(300);self.command('recover','recover',reason='重启')
        self.assertEqual(self.p.snapshot()['activities'][step['id']]['progress'],120)
        self.assertEqual(self.p.snapshot()['activities'][step['id']]['status'],'failed')
        with self.assertRaisesRegex(ValueError,'cannot resume'):
            self.command('resume2','resume',activity_id=step['id'])

    def test_boundary_cancels_remaining_phases_without_finishing_cases(self):
        step=skill.prepare(self.cog)['steps'][0];self.start_step(step);self.ticks(60)
        self.item.update(id='lunch-now',state_type='eating',activity='lunch',intent='用餐',kind='meal')
        self.assertTrue(pause_mismatch(self.cog))
        self.assertEqual(self.p.snapshot()['activities'][step['id']]['status'],'failed')
        untouched=[x for x in self.p.snapshot()['work_steps'].values() if x['id']!=step['id']]
        self.assertTrue(all(x['progress']==0 and not x.get('ended_at') for x in untouched))

    def test_court_has_arrival_and_actual_departure_only(self):
        for place,name in [('court','未名市法院'),('procuratorate','未名市检察院')]:
            self.p.config['places'][place]={'name':name,'parent':None,'status':'confirmed','source':'fixture'}
            self.p.config['household_world']['edges'].append(['firm',place])
            self.slot(place,minutes=2,ident=place);self.set_place(place)
            step=skill.prepare(self.cog)['steps'][0];self.start_step(step);self.ticks(60)
            self.command('pause:'+place,'interrupt',activity_id=step['id'],reason='用户互动')
            self.command('resume:'+place,'resume',activity_id=step['id']);self.ticks(60)
            with self.p.store.connect() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='work_departure'").fetchone()[0],0 if place=='court' else 1)
            self.move('firm.office','leave:'+place)
        with self.p.store.connect() as db:
            rows=db.execute("SELECT kind,description FROM events WHERE kind LIKE 'work_%'").fetchall()
            self.assertEqual([r[0] for r in rows],['work_arrival','work_departure']*2)

    def test_home_independent_tasks_and_client_field_modes(self):
        self.slot('home.f2.study');self.set_place('home.f2.study')
        steps=skill.prepare(self.cog)['steps']
        self.assertTrue(all(s['task'] in {'materials','research','contract','notes'} and s['place']=='home.f2.study' for s in steps))
        self.p.config['places']['client']={'name':'客户公司','parent':None}
        self.p.config['places']['police']={'name':'某警局','parent':None}
        self.assertEqual(skill.category(self.p.config,'client'),'client')
        self.assertEqual(skill.category(self.p.config,'police'),'field')

    def test_agent_tool_and_action_bypass_legacy_work_artifacts(self):
        self.slot(minutes=30)
        from life_prototype.scheduler import Scheduler,DEFAULTS
        from life_prototype.autonomous_agent import LifeAgent
        agent=LifeAgent(Scheduler(self.chat,DEFAULTS))
        step=agent._tool('prepare','work.prepare',{})['steps'][0]
        result=agent._action('work-agent',{'expected_revision':self.p.snapshot()['revision'],
            'action':{'operation':'start','activity_id':None,'kind':'work','target':step['id']},'movement_purpose':None})
        self.assertIsNotNone(result['active_activity'])
        from life_prototype.state_view import progress_view
        self.assertEqual(progress_view(self.p.snapshot()['activities'][result['active_activity']],self.p.config)['target_name'],step['title'])
        from life_prototype.home_world import evaluate
        with self.assertRaises(ValueError):evaluate(self.p,self.p.snapshot(),self.clock.now())

    def test_office_catalog_all_rooms_routes_and_persistent_install(self):
        from life_prototype.meal_places import install
        self.assertTrue(install(self.cog));self.assertTrue(install(self.cog))
        from life_prototype.home_world import path
        for key in firm_catalog.ROOMS:self.assertTrue(path(self.p.config,'firm.office','firm.'+key))
        with self.p.store.connect() as db:
            stored=json.loads(db.execute("SELECT body FROM life_state WHERE name='work_extension'").fetchone()[0])
        self.assertIn('firm.zhai_office',stored['config']['places'])

    def test_agent_moves_to_saved_office_phase_not_coarse_office(self):
        ident=next('move'+str(i) for i in range(100) if int(digest('move'+str(i))[:8],16)%4==0)
        self.slot(ident=ident);saved=skill.prepare(self.cog)
        desired=requirement(self.cog)
        self.assertEqual(desired['destination'],'firm.open_office')
        from life_prototype.scheduler import Scheduler,DEFAULTS
        from life_prototype.autonomous_agent import LifeAgent
        agent=LifeAgent(Scheduler(self.chat,DEFAULTS))
        from life_prototype.coarse_locations import advance
        advance(self.cog)
        self.assertEqual(self.p.snapshot()['place'], desired['destination'])
        result=agent._action('work-room',{'expected_revision':self.p.snapshot()['revision'],
            'action':{'operation':'start','activity_id':None,'kind':'work','target':desired['targets'][0]},
            'movement_purpose':None})
        self.assertIsNotNone(result['active_activity'])
        self.assertFalse(any(a['kind']=='moving' for a in self.p.snapshot()['activities'].values()))

    def test_expired_phase_cannot_be_resumed_in_later_work_slot(self):
        self.slot(minutes=1);step=skill.prepare(self.cog)['steps'][0];self.start_step(step)
        self.command('pause','interrupt',activity_id=step['id'],reason='互动')
        self.clock.advance(120)
        with self.assertRaises(ValueError):self.command('late-resume','resume',activity_id=step['id'])
        self.slot(minutes=30,ident='later');new=skill.prepare(self.cog)
        self.assertNotEqual(new['steps'][0]['id'],step['id'])


if __name__=='__main__':unittest.main()
