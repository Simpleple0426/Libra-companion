from datetime import timedelta
import json
import unittest
import test_meal_skill as fixture
from life_prototype.config import canonical
from life_prototype.state_schema import facts_only
from life_prototype.event_assimilation import validate_update,observation_input
from scripts.retire_life_needs import migrate


class FactsOnlyTests(unittest.TestCase):
    setUp=fixture.MealSkillTests.setUp

    def test_new_state_and_llm_contract_have_no_scores(self):
        state=self.p.snapshot()
        self.assertTrue(state['cognition_enabled'])
        self.assertNotIn('needs',state)
        observation={'id':'obs:1','type':'self_activity','fact':{},'allowed_dimensions':['hunger']}
        context={**self.cog._snapshot(),'observation':observation}
        payload=observation_input(context)
        self.assertNotIn('allowed_dimensions',payload['observation'])
        output={'importance':3,'keywords':['事实'],'summary':'记录实际活动','evidence_ids':['obs:1']}
        validate_update(output,payload)
        with self.assertRaises(ValueError):validate_update({**output,'needs':{'hunger':5}},payload)

    def test_elapsed_sleep_and_natural_wake_without_sleepiness(self):
        now=self.clock.now()
        with self.p.store.connect() as db:
            state=self.p.store.read(db)
            episode={'id':'sleep:test','started_at':now.isoformat(),'settled_until':now.isoformat(),
                     'natural_wake_at':(now+timedelta(seconds=600)).isoformat(),'seconds':0}
            state['sleep'].update(status='sleeping',current=episode['id'],episodes=[episode])
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
        self.clock.advance(120);self.chat.tick('sleep:first')
        self.assertEqual(self.p.snapshot()['sleep']['total_seconds'],120)
        self.chat.tick('sleep:first')
        self.assertEqual(self.p.snapshot()['sleep']['total_seconds'],120)
        self.clock.advance(480);self.chat.tick('sleep:end')
        state=self.p.snapshot()
        self.assertEqual(state['sleep']['status'],'awake')
        self.assertEqual(state['sleep']['total_seconds'],600)
        self.assertNotIn('needs',state)
        self.assertNotIn('recovery_remainder_seconds',state['sleep'])

    def test_migration_preserves_progress_and_requeues_contract_work(self):
        from life_prototype.scheduler import Scheduler,DEFAULTS
        Scheduler(self.chat,DEFAULTS)
        with self.p.store.connect() as db:
            state=self.p.store.read(db)
            state.update(needs={'hunger':5,'sleepiness':5},need_revision=2,need_source='old')
            state['reading']={'book':150};state['viewing']={'movie':200}
            state['sleep']['recovery_remainder_seconds']=30
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
            db.execute("INSERT INTO life_scheduler_jobs VALUES('old','sync','{}','running',1,NULL,NULL)")
            report=migrate(db)
            after=self.p.store.read(db)
            self.assertNotIn('needs',after)
            self.assertEqual(after['reading'],state['reading']);self.assertEqual(after['viewing'],state['viewing'])
            self.assertEqual(after['sleep']['total_seconds'],state['sleep']['total_seconds'])
            self.assertEqual(report['replaced_jobs'],['old'])
            self.assertEqual(db.execute("SELECT count(*) FROM life_scheduler_jobs WHERE status='pending'").fetchone()[0],1)
            self.assertTrue(migrate(db)['already_migrated'])

    def test_old_snapshot_projection_keeps_real_progress(self):
        old={'snapshot':{'needs':{'hunger':9},'need_revision':3,'reading':{'book':20}},
             'dimensions':{'hunger':'score','sleepiness':'score'},'text':'原始事件文字'}
        clean=facts_only(old)
        self.assertEqual(clean,{'snapshot':{'reading':{'book':20}},'text':'原始事件文字'})
        self.assertIn('needs',old['snapshot'])


if __name__=='__main__':unittest.main()
