from datetime import timedelta
import json
from unittest.mock import patch
import unittest
import test_meal_skill as fixture
from life_prototype import skill_outing as skill, outing_content as content
from life_prototype.coarse_plan_schema import detail_kinds,pack_item,unpack_item
from life_prototype.coarse_plan_execution import requirement,pause_mismatch


class OutingModel:
    provider='isolated-test';kind='fixture'
    def __init__(self):self.calls=[];self.hook=None
    def complete(self,stage,payload):
        self.calls.append((stage,payload))
        if self.hook:self.hook(stage)
        if stage=='outing_query':return {'query':'推理小说'},{}
        if stage=='outing_choose':return {'book_id':payload['candidates'][0]['selection_id']},{}
        if stage=='outing_intro':return {'body':'这本书讨论选择与责任，是让我愿意带回去慢慢读的题目。还没有读过正文，先把它放在书架上。之后如果你有兴趣，我也想听听你的看法。'},{}
        if stage=='outing_walk':return {'body':'这段路适合慢慢走。忽然想，下次如果你愿意，我们可以一起过来，不必赶时间。'},{}
        raise AssertionError(stage)


class OutingTests(unittest.TestCase):
    def setUp(self):
        fixture.MealSkillTests.setUp(self)
        from life_prototype import weread
        guard=patch.object(weread,'status',return_value={'configured':False})
        guard.start();self.addCleanup(guard.stop)
    command=fixture.MealSkillTests.command

    def setup_outing(self,kind='bookstores',ident='outing'):
        from life_prototype.meal_places import configured
        names={'bookstores':'西里卡书店','walks':'未名步道','shopping':'滨河中心商场'}
        self.p.config=configured(self.p.config,{'locations':{kind:[names[kind]]}})
        place=next(k for k,v in self.p.config['places'].items() if v['name']==names[kind])
        self.item.update(id=ident,state_type='free',kind='free',activity='outing',intent='外出活动',place=place,
                         end_at=(self.clock.now()+timedelta(minutes=30)).isoformat())
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['place']=place
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(json.dumps(state),))
        self.model=OutingModel();self.cog.calls.model=self.model
        plan=skill.prepare(self.cog)['outing']
        self.command('start:'+ident,'start',activity_id=ident,kind='outing',target=plan['id'])
        return plan

    def source(self,operation,**args):
        if operation=='search':return [{'id':'123','title':'新的推理小说'},{'id':'124','title':'另一本书'}]
        return {'id':args['douban_id'],'title':'新的推理小说' if args['douban_id']=='123' else '另一本书',
                'authors':['测试作者'],'isbn':'9780000000'+args['douban_id'],
                'summary':'一部通过人物抉择讨论责任的推理小说。'}

    def rows(self,table):
        with self.p.store.connect() as db:return db.execute('SELECT * FROM '+table).fetchall()

    def test_book_purchase_one_draft_persists_and_does_not_become_readable(self):
        self.setup_outing();before=set(self.p.config['books'])
        with patch.object(content.Douban,'book_call',side_effect=self.source):
            self.assertTrue(content.process_one(self.cog));self.assertFalse(content.process_one(self.cog))
        data=content.saved(self.cog)
        self.assertEqual(len(data['owned_books']),1);self.assertEqual(len(data['drafts']),1)
        self.assertEqual(data['drafts'][0]['status'],'pending_display')
        self.assertIsNone(data['drafts'][0]['published_at'])
        self.assertFalse(data['owned_books'][0]['reading_available'])
        self.assertEqual(before,set(self.p.config['books']))
        self.assertEqual(len([r for r in self.rows('events') if r[3]=='book_purchased']),1)
        self.assertTrue(data['drafts'][0]['sources'][0].startswith('https://book.douban.com/subject/'))

    def test_same_physical_visit_after_schedule_change_cannot_buy_second(self):
        self.setup_outing()
        with patch.object(content.Douban,'book_call',side_effect=self.source):content.process_one(self.cog)
        self.command('pause','interrupt',activity_id='outing',reason='日程修订')
        self.setup_outing(ident='revised')
        self.assertFalse(content.process_one(self.cog));self.assertEqual(len(self.rows('life_owned_books')),1)
        self.assertEqual(len(self.rows('life_outing_jobs')),1)

    def test_library_and_other_editions_are_deduplicated(self):
        self.setup_outing()
        self.p.config['books']['already']={'title':'新的推理小说（新版）','author':'测试作者'}
        self.p.config['books']['already2']={'title':'另一本书','author':'测试作者'}
        with patch.object(content.Douban,'book_call',side_effect=self.source):content.process_one(self.cog)
        self.assertFalse(self.rows('life_owned_books'));self.assertFalse(self.rows('life_dynamic_drafts'))
        self.assertEqual(self.rows('life_outing_jobs')[0][1],'skipped')
        self.assertTrue(content.duplicate({'title':'翻译不同','isbn':'978-1'},[{'title':'原书','isbn':'9781'}]))

    def test_library_added_during_search_is_rechecked_at_commit(self):
        self.setup_outing()
        def hook(stage):
            if stage=='outing_intro':self.p.config['books']['newly-imported']={'title':'新的推理小说'}
        self.model.hook=hook
        with patch.object(content.Douban,'book_call',side_effect=self.source):content.process_one(self.cog)
        self.assertFalse(self.rows('life_owned_books'))

    def test_late_search_result_cannot_buy_after_leaving(self):
        self.setup_outing()
        def hook(stage):
            if stage=='outing_intro':self.command('leave-now','interrupt',activity_id='outing',reason='离开')
        self.model.hook=hook
        with patch.object(content.Douban,'book_call',side_effect=self.source):content.process_one(self.cog)
        self.assertFalse(self.rows('life_owned_books'));self.assertFalse(self.rows('life_dynamic_drafts'))
        self.assertEqual(self.rows('life_outing_jobs')[0][1],'cancelled')

    def test_failed_mcp_does_not_block_life_or_invent_purchase(self):
        self.setup_outing()
        with patch.object(content.Douban,'book_call',side_effect=RuntimeError('offline')):content.process_one(self.cog)
        self.assertFalse(self.rows('life_owned_books'));self.assertEqual(self.p.snapshot()['active'],'outing')
        self.clock.advance(1800);skill.heartbeat(self.cog)
        self.assertIsNone(self.p.snapshot()['active'])

    def test_walk_thought_once_with_user_context_and_no_network(self):
        self.setup_outing('walks')
        with patch.object(content.Douban,'book_call',side_effect=AssertionError('unexpected network')):
            content.process_one(self.cog);content.process_one(self.cog)
        draft=content.saved(self.cog)['drafts'][0]
        self.assertEqual(draft['kind'],'walk_thought');self.assertIn('你',draft['body'])
        self.assertEqual(self.model.calls[0][0],'outing_walk')
        self.assertIn('memories',self.model.calls[0][1]);self.assertEqual(self.model.calls[0][1]['observations'],[])
        self.assertEqual(len(self.rows('life_dynamic_drafts')),1)

    def test_generic_events_no_content_job_and_specific_skills_priority(self):
        self.setup_outing('shopping');self.clock.advance(1800);skill.heartbeat(self.cog)
        events=[r[2] for r in self.rows('events') if r[3].startswith('outing_')]
        self.assertEqual(events,['左然开始购物','左然结束了购物'])
        self.assertEqual(self.model.calls,[])
        with self.p.store.connect() as db:content.initialize(db)
        for intent in ['阅读','看电影','运动','休息','用餐','工作']:
            self.assertFalse(skill.routine({**self.item,'intent':intent}))
        self.assertEqual(detail_kinds(unpack_item(pack_item(self.item))),set())

    def test_real_departure_resets_visit_but_owned_books_remain_excluded(self):
        self.setup_outing()
        with patch.object(content.Douban,'book_call',side_effect=self.source):content.process_one(self.cog)
        self.command('pause-first','interrupt',activity_id='outing',reason='离开书店')
        from coarse_location_fixture import depart
        depart(self, 'firm.office')
        self.assertNotIn('outing_visit',self.p.snapshot())
        self.setup_outing(ident='second-visit')
        with patch.object(content.Douban,'book_call',side_effect=self.source):content.process_one(self.cog)
        self.assertEqual(len(self.rows('life_owned_books')),2)
        self.assertEqual({json.loads(r[-1])['title'] for r in self.rows('life_owned_books')},{'新的推理小说','另一本书'})

    def test_retry_reuses_fetched_candidates_and_writes_once(self):
        self.setup_outing()
        def fail(stage):
            if stage=='outing_intro':raise RuntimeError('model temporary failure')
        self.model.hook=fail
        with patch.object(content.Douban,'book_call',side_effect=self.source):content.process_one(self.cog)
        self.assertFalse(self.rows('life_owned_books'))
        self.clock.advance(301);self.model.hook=None
        with patch.object(content.Douban,'book_call',side_effect=AssertionError('must reuse saved candidates')):
            content.process_one(self.cog);content.process_one(self.cog)
        self.assertEqual(len(self.rows('life_owned_books')),1)
        self.assertEqual(len(self.rows('life_dynamic_drafts')),1)

    def test_agent_contract_saved_visit_and_content_survive_reopen(self):
        self.setup_outing('walks')
        from life_prototype.scheduler import Scheduler,DEFAULTS
        from life_prototype.autonomous_agent import LifeAgent
        agent=LifeAgent(Scheduler(self.chat,DEFAULTS))
        self.assertEqual(agent._tool('read-outing','outing.prepare',{})['outing']['category'],'walk')
        agent._action('continue-outing',{'expected_revision':self.p.snapshot()['revision'],
            'action':{'operation':'continue','activity_id':'outing','kind':'outing','target':'outing:outing'},'movement_purpose':None})
        from life_prototype.home_world import evaluate
        with self.assertRaises(ValueError):evaluate(self.p,self.p.snapshot(),self.clock.now())
        content.process_one(self.cog)
        with self.p.store.connect() as db:
            persisted=self.p.store.read(db)
            self.assertEqual(persisted['outing_visit']['id'],persisted['activities']['outing']['visit_id'])
            self.assertEqual(db.execute("SELECT count(*) FROM life_dynamic_drafts WHERE status='pending_display'").fetchone()[0],1)
        self.command('recover-outing','recover',reason='restart')
        self.assertFalse(content.process_one(self.cog))
        self.assertEqual(len(content.saved(self.cog)['drafts']),1)


if __name__=='__main__':unittest.main()
