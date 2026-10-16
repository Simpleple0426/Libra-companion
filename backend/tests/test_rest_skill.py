from datetime import timedelta
import json
import unittest
import test_meal_skill as fixture
from life_prototype import skill_rest as skill
from life_prototype.coarse_plan_execution import requirement, pause_mismatch
from life_prototype.coarse_plan_schema import detail_kinds, pack_item, unpack_item


class RestTests(unittest.TestCase):
    setUp=fixture.MealSkillTests.setUp
    command=fixture.MealSkillTests.command

    def prepare(self):
        self.item.update(id='rest',state_type='resting',kind='resting',activity='resting',intent='休息',
                         place='home.f1.living',end_at=(self.clock.now()+timedelta(minutes=5)).isoformat())
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['place']=self.item['place']
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(json.dumps(state),))
        return skill.prepare(self.cog)['rest']

    def start(self):
        plan=self.prepare()
        self.command('rest-start','start',activity_id='rest',kind='rest',target=plan['id'])
        return plan

    def events(self):
        with self.p.store.connect() as db:
            return [r[0] for r in db.execute("SELECT description FROM events WHERE kind IN ('rest_start','rest_end') ORDER BY rowid")]

    def test_rest_starts_ends_once_and_stays_awake(self):
        plan=self.start();self.clock.advance(60);skill.heartbeat(self.cog)
        self.assertEqual(self.events(),['左然开始休息'])
        self.clock.advance(240);skill.heartbeat(self.cog);skill.heartbeat(self.cog)
        self.assertEqual(self.events(),['左然开始休息','左然结束了休息'])
        self.assertEqual(self.p.snapshot()['sleep']['status'],'awake')
        self.assertEqual(self.model.calls,[])
        self.cog.ingest();self.cog.ingest()
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM life_memories WHERE description IN (?,?)",tuple(self.events())).fetchone()[0],2)

    def test_specific_intents_override_resting_after_serialization(self):
        self.prepare()
        for intent,kinds in [('阅读',{'reading'}),('看电影',{'watching'}),('看电视',set())]:
            self.item['intent']=intent
            parent=unpack_item(pack_item(self.item))
            self.assertFalse(skill.routine(parent))
            self.assertEqual(detail_kinds(parent),kinds)
            required=requirement(self.cog)
            self.assertNotIn(required['reason'],{'reserved_time','call_rest_prepare'})
        self.item['intent']='看电视'
        self.assertEqual(requirement(self.cog)['reason'],'call_television_prepare')

    def test_empty_intent_fallback_but_free_and_bedtime_are_not_rest(self):
        self.prepare();self.item['intent']=None
        self.assertTrue(skill.routine(self.item))
        self.assertTrue(skill.routine({**self.item,'state_type':'free','intent':'休息'}))
        self.assertFalse(skill.routine({'state_type':'free','activity':'free'}))
        self.assertFalse(skill.routine({**self.item,'activity':'bedtime_preparation'}))
        self.assertFalse(skill.routine({**self.item,'intent':'准备睡觉'}))
        self.assertFalse(skill.routine({**self.item,'activity':'reading'}))

    def test_boundary_or_recovery_ends_once(self):
        plan=self.start();self.item['intent']='看电视'
        self.assertTrue(pause_mismatch(self.cog))
        self.command('recover','recover',reason='restart')
        self.assertEqual(self.events(),['左然开始休息','左然结束了休息'])
        with self.assertRaises(ValueError): self.command('again','start',activity_id='rest2',kind='rest',target=plan['id'])

    def test_recovery_of_active_rest_and_agent_contract(self):
        plan=self.prepare()
        from life_prototype.scheduler import Scheduler, DEFAULTS
        from life_prototype.autonomous_agent import LifeAgent
        agent=LifeAgent(Scheduler(self.chat,DEFAULTS))
        self.assertEqual(agent._tool('prepare','rest.prepare',{})['rest']['id'],plan['id'])
        agent._action('rest-agent',{'expected_revision':self.p.snapshot()['revision'],
            'action':{'operation':'start','activity_id':None,'kind':'rest','target':plan['id']},'movement_purpose':None})
        from life_prototype.home_world import evaluate
        with self.assertRaises(ValueError): evaluate(self.p,self.p.snapshot(),self.clock.now())
        self.clock.advance(3600);self.command('recover-active','recover',reason='restart')
        self.assertEqual(self.events(),['左然开始休息','左然结束了休息'])
        self.assertEqual(self.p.snapshot()['sleep']['status'],'awake')


if __name__=='__main__': unittest.main()
