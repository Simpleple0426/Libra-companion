from datetime import timedelta
import json
import unittest
import test_meal_skill as fixture
from life_prototype import skill_television as skill
from life_prototype.coarse_plan_execution import requirement, pause_mismatch
from life_prototype.coarse_plan_schema import detail_kinds, pack_item, unpack_item
from life_prototype.state_view import progress_view


class TelevisionTests(unittest.TestCase):
    setUp=fixture.MealSkillTests.setUp
    command=fixture.MealSkillTests.command

    def prepare(self):
        self.item.update(id='tv',state_type='free',kind='free',activity='watch_tv',intent='看电视',
                         place='home.f1.living',end_at=(self.clock.now()+timedelta(minutes=5)).isoformat())
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['place']=self.item['place']
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(json.dumps(state),))
        return skill.prepare(self.cog)['television']

    def start(self):
        plan=self.prepare()
        self.command('on','start',activity_id='tv',kind='television',target=plan['id'])
        return plan

    def events(self):
        with self.p.store.connect() as db:
            return [r[0] for r in db.execute("SELECT description FROM events WHERE kind LIKE 'television_%' ORDER BY rowid")]

    def test_start_end_only_no_content_progress_or_model_calls(self):
        plan=self.start();self.clock.advance(60);skill.heartbeat(self.cog)
        active=self.p.snapshot()['activities']['tv']
        self.assertNotIn('progress',progress_view(active,self.p.config))
        self.assertNotIn('programme',self.p.snapshot()['television_sessions'][plan['id']])
        self.assertEqual(self.events(),['左然打开了电视'])
        self.clock.advance(240);skill.heartbeat(self.cog)
        self.assertEqual(self.events(),['左然打开了电视','左然关掉了电视'])
        self.assertEqual(self.p.snapshot()['television_sessions'][plan['id']]['power'],'off')
        self.assertFalse(skill.heartbeat(self.cog))
        self.assertEqual(self.model.calls,[])
        self.cog.ingest();self.cog.ingest()
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM life_memories WHERE description IN (?,?)",tuple(self.events())).fetchone()[0],2)

    def test_coarse_change_closes_and_session_cannot_reopen(self):
        plan=self.start();self.item.update(intent='阅读',activity='reading')
        self.assertTrue(pause_mismatch(self.cog))
        self.item.update(intent='看电视',activity='watch_tv')
        self.assertEqual(requirement(self.cog)['mode'],'hold')
        with self.assertRaises(ValueError): self.command('again','start',activity_id='tv2',kind='television',target=plan['id'])
        with self.assertRaises(ValueError): self.command('resume','resume',activity_id='tv')
        self.assertEqual(self.events(),['左然打开了电视','左然关掉了电视'])

    def test_recovery_closes_once_without_backdated_event(self):
        self.start();self.clock.advance(3600)
        self.command('restart','recover',reason='restart')
        self.command('restart2','recover',reason='restart')
        self.assertEqual(self.events(),['左然打开了电视','左然关掉了电视'])
        self.assertEqual(self.p.snapshot()['activities']['tv']['completed_at'],self.clock.now().isoformat())

    def test_preparation_is_not_on_event_and_requires_real_tv(self):
        plan=self.prepare();self.assertEqual(self.events(),[])
        self.assertEqual(skill.prepare(self.cog)['television']['id'],plan['id'])
        self.p.config['objects'][plan['device']]['available']=False
        self.assertEqual(requirement(self.cog)['reason'],'no_catalogued_television_here')
        with self.assertRaises(ValueError): self.command('bad','start',activity_id='tv',kind='television',target=plan['id'])
        self.assertEqual(self.events(),[])

    def test_packed_routing_agent_action_and_result_guard(self):
        plan=self.prepare();packed=unpack_item(pack_item(self.item))
        self.assertTrue(skill.routine(packed));self.assertEqual(detail_kinds(packed),set())
        self.assertFalse(skill.routine({**packed,'intent':'看电影','activity':'watch_movie'}))
        from life_prototype.scheduler import Scheduler, DEFAULTS
        from life_prototype.autonomous_agent import LifeAgent
        agent=LifeAgent(Scheduler(self.chat,DEFAULTS))
        self.assertEqual(agent._tool('prepare','television.prepare',{})['television']['id'],plan['id'])
        agent._action('tv-agent',{'expected_revision':self.p.snapshot()['revision'],
            'action':{'operation':'start','activity_id':None,'kind':'television','target':plan['id']},'movement_purpose':None})
        from life_prototype.home_world import evaluate
        with self.assertRaises(ValueError): evaluate(self.p,self.p.snapshot(),self.clock.now())


if __name__=='__main__': unittest.main()
