from datetime import timedelta
from copy import deepcopy
import json
import unittest
import test_meal_skill as fixture
from life_prototype import skill_housework as skill
from life_prototype.clock import utc
from life_prototype.coarse_plan_execution import requirement
from life_prototype.coarse_plan_schema import pack_item,unpack_item,detail_kinds
from life_prototype.home_world import checkpoint


class HouseworkTests(unittest.TestCase):
    setUp=fixture.MealSkillTests.setUp
    command=fixture.MealSkillTests.command

    def slot(self,name='housework',place='home.f1.living',minutes=60,ident='chores'):
        self.item.update(id=ident,state_type='free',activity=name,intent='家务',place=place,reference_id=None,
            start_at=self.clock.now().isoformat(),end_at=(self.clock.now()+timedelta(minutes=minutes)).isoformat())

    def set_place(self,place):
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['place']=place
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(json.dumps(state),))

    def ticks(self,seconds):
        while seconds>0:
            part=min(seconds,60);self.clock.advance(part);skill.heartbeat(self.cog);seconds-=part

    def execute_plan(self,plan):
        for ident in plan['step_ids']:
            step=self.p.snapshot()['housework_steps'][ident]
            if step.get('completed_at'): continue
            from life_prototype.coarse_locations import advance
            advance(self.cog)
            self.command(ident,'start',activity_id=ident,kind='housework',target=ident)
            self.ticks(step['seconds']-step['progress'])

    def test_catalog_chore_events_and_memories_are_idempotent(self):
        self.slot();self.set_place('home.f1.living')
        plan=skill.prepare(self.cog)['housework'];self.execute_plan(plan)
        self.cog.ingest();self.cog.ingest()
        self.assertEqual(requirement(self.cog)['mode'],'hold')
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='housework_completed'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM life_memories WHERE id=?",('mem:housework-finished:'+plan['step_ids'][0],)).fetchone()[0],1)
        self.assertEqual(self.model.calls,[])

    def test_laundry_runs_while_away_but_never_hangs_itself(self):
        self.slot('laundry','home.f1.balcony')
        plan=skill.prepare(self.cog)['housework'];self.execute_plan(plan)
        state=self.p.snapshot();machine=next(iter(state['household_machines'].values()))
        self.assertEqual(machine['status'],'running')
        self.set_place('home.f2.study');self.clock.advance(skill.WASH_SECONDS)
        self.assertTrue(skill.tick_machines(self.cog));self.assertFalse(skill.tick_machines(self.cog))
        state=self.p.snapshot()
        self.assertEqual(state['place'],'home.f2.study')
        self.assertEqual(state['laundry_batches'][machine['id']]['status'],'washed')
        self.assertEqual(skill.steps_for(self.p.config,state,self.item)[1],'finish_existing_laundry_first')
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='household_machine_completed'").fetchone()[0],1)

    def test_full_laundry_to_hang_dry_and_store(self):
        self.slot('laundry','home.f1.balcony');self.execute_plan(skill.prepare(self.cog)['housework'])
        self.clock.advance(skill.WASH_SECONDS);skill.tick_machines(self.cog)
        self.slot('dry_laundry','home.f1.balcony',ident='hang')
        self.execute_plan(skill.prepare(self.cog)['housework'])
        batch=next(iter(self.p.snapshot()['laundry_batches'].values()))
        self.assertEqual(batch['status'],'airing')
        self.clock.advance(skill.AIR_SECONDS);skill.tick_machines(self.cog)
        # A later generic chore slot also notices laundry instead of leaving it forever.
        self.slot('housework','home.f1.living',ident='fold')
        self.execute_plan(skill.prepare(self.cog)['housework'])
        batch=next(iter(self.p.snapshot()['laundry_batches'].values()))
        self.assertEqual(batch['status'],'stored')
        self.assertEqual(batch['place'],'home.f2.dressing')

    def test_no_automatic_hang_without_washed_batch(self):
        self.slot('dry_laundry','home.f1.balcony')
        self.assertEqual(requirement(self.cog)['mode'],'hold')
        with self.assertRaises(ValueError): skill.prepare(self.cog)

    def test_restart_preserves_machine_timer_without_duplicate_event(self):
        self.slot('laundry','home.f1.balcony');self.execute_plan(skill.prepare(self.cog)['housework'])
        from life_prototype.activity_engine import Prototype
        from types import SimpleNamespace
        reopened=Prototype('meal',self.world,self.clock,root=self.root)
        other=SimpleNamespace(p=reopened,store=reopened.store,clock=self.clock)
        self.clock.advance(skill.WASH_SECONDS)
        self.assertTrue(skill.tick_machines(other));self.assertFalse(skill.tick_machines(self.cog))

    def test_pause_recovery_does_not_credit_human_offline_time(self):
        self.slot();self.set_place('home.f1.living');plan=skill.prepare(self.cog)['housework']
        target=plan['step_ids'][0];self.command('start','start',activity_id='tidy',kind='housework',target=target)
        self.ticks(60);self.clock.advance(300);self.command('recover','recover',reason='restart')
        self.assertEqual(self.p.snapshot()['activities']['tidy']['progress'],60)
        self.assertEqual(self.p.snapshot()['activities']['tidy']['status'],'failed')
        self.assertIsNone(self.p.snapshot()['active'])
        with self.assertRaisesRegex(ValueError,'cannot resume'):
            self.command('resume','resume',activity_id='tidy')
        self.ticks(60)
        self.assertEqual(self.p.snapshot()['housework_steps'][target]['progress'],60)
        self.assertNotIn('completed_at',self.p.snapshot()['housework_steps'][target])

    def test_missing_catalog_device_cannot_be_invented(self):
        self.slot('laundry','home.f1.balcony')
        ident=skill.object_named(self.p.config,'洗衣机');self.p.config['objects'].pop(ident)
        self.assertEqual(requirement(self.cog)['reason'],'washing_machine_missing')
        with self.assertRaises(ValueError): skill.prepare(self.cog)

    def test_coarse_serialization_preserves_explicit_chore(self):
        self.slot('laundry','home.f1.balcony')
        packed=pack_item(self.item);unpacked=unpack_item(packed)
        self.assertEqual(skill.routine(unpacked),'laundry');self.assertEqual(detail_kinds(unpacked),set())
        packed.pop('constraints');packed['source_window']=['dry_laundry','阳台',None,None]
        self.assertEqual(skill.routine(unpack_item(packed)),'dry_laundry')

    def test_movement_purpose_and_agent_action_use_saved_phase(self):
        self.slot('laundry','home.f1.balcony');plan=skill.prepare(self.cog)['housework']
        desired=requirement(self.cog)
        from life_prototype.scheduler import Scheduler,DEFAULTS
        from life_prototype.autonomous_agent import LifeAgent
        agent=LifeAgent(Scheduler(self.chat,DEFAULTS))
        from life_prototype.coarse_locations import advance
        advance(self.cog)
        self.assertEqual(self.p.snapshot()['place'],desired['destination'])
        result=agent._action('housework-room',{'expected_revision':self.p.snapshot()['revision'],
            'action':{'operation':'start','activity_id':None,'kind':'housework','target':desired['targets'][0]},
            'movement_purpose':None})
        self.assertIsNotNone(result['active_activity'])
        self.assertFalse(any(a['kind']=='moving' for a in self.p.snapshot()['activities'].values()))

    def test_budget_boundary_and_next_slot_resume_same_step(self):
        self.slot(minutes=3);self.set_place('home.f1.living');plan=skill.prepare(self.cog)['housework'];target=plan['step_ids'][0]
        self.command('start','start',activity_id='tidy',kind='housework',target=target);self.ticks(60)
        self.command('pause','interrupt',activity_id='tidy',reason='message');self.clock.advance(120)
        self.assertNotIn('completed_at',self.p.snapshot()['housework_steps'][target])
        self.slot(ident='next');new=skill.prepare(self.cog)['housework']
        self.assertEqual(new['id'],plan['id'])
        self.command('resume','resume',activity_id='tidy');self.ticks(60)
        self.assertEqual(self.p.snapshot()['activities']['tidy']['status'],'completed')

    def test_dishes_follow_actual_paths_and_phase_order(self):
        self.slot('clean_dishes','home.f1.kitchen');plan=skill.prepare(self.cog)['housework']
        with self.assertRaises(ValueError): self.command('wrong','start',activity_id='wrong',kind='housework',target=plan['step_ids'][1])
        self.execute_plan(plan)
        state=self.p.snapshot();self.assertIn('completed_at',state['housework_plans'][plan['id']])
        self.assertEqual(state['place'],'home.f1.kitchen')

    def test_generic_rotation_includes_wiping_and_independent_robot(self):
        for i in range(3):
            self.slot(ident='chore:'+str(i))
            self.execute_plan(skill.prepare(self.cog)['housework'])
        machines=list(self.p.snapshot()['household_machines'].values())
        self.assertEqual([m['type'] for m in machines],['vacuum'])
        self.clock.advance(600);skill.tick_machines(self.cog);self.cog.ingest();self.cog.ingest()
        with self.p.store.connect() as db:
            rows=[r[0] for r in db.execute("SELECT description FROM events WHERE kind='household_machine_completed'")]
            self.assertEqual(len(rows),1);self.assertIn('扫地机器人',rows[0])
            event='household-timer:'+machines[0]['id']
            self.assertEqual(db.execute('SELECT COUNT(*) FROM life_memories WHERE id=?',('mem:'+event,)).fetchone()[0],1)


if __name__=='__main__': unittest.main()
