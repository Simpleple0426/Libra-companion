from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from application.diet_preferences import normalize, read, save
from app.api.models import PersonalizationSettingRequest
from life_prototype.clock import TestClock
from life_prototype.activity_engine import Prototype
from life_prototype.local_configuration import configurations
from life_prototype.cognition import Cognition
from life_prototype import skill_dining as meal_skill
from life_prototype.state_view import progress_view


class MealModel:
    provider='isolated-test'
    kind='fixture'
    def __init__(self): self.mode='cook'; self.calls=[]; self.spicy=False
    def complete(self,stage,payload):
        self.calls.append((stage,payload))
        option=next(row for row in payload['options'] if row['mode']==self.mode)
        breakfast=payload['coarse_item'].get('activity')=='breakfast'
        dishes=['燕麦粥','煎蛋','咖啡'] if breakfast else ['麻辣鱼' if self.spicy else '清蒸鱼']
        return {'mode':self.mode,'place':option['place'],'dishes':dishes,
                'spice':'none','user_consideration':'参考用户喜欢鱼的偏好，想下次问问她的口味。','reason':'适合本次时间'},{}


class MealSkillTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.world,config,sleep_config,*_=configurations()
        self.world['initial']['place']='home.f1.kitchen'
        self.world['places']['test.restaurant']={'name':'手工披萨店','parent':None,'status':'confirmed','source':'fixture'}
        self.world['household_world']['edges'].append(['firm.office','test.restaurant'])
        self.world['household_world']['edges'].append(['home.f1','firm.office'])
        self.clock=TestClock('2026-09-28T12:00:00+08:00')
        self.p=Prototype('meal',self.world,self.clock,root=self.root)
        self.model=MealModel(); self.cog=Cognition(self.p,self.model,config)
        from life_prototype.interaction import Interaction
        self.chat=Interaction(self.cog,sleep_config)
        self.cog.resource_root=self.root
        folder=self.root/'libra/world';folder.mkdir(parents=True)
        (folder/'schedule_rules.json').write_text(json.dumps({'locations':{'restaurants':['手工披萨店']}}),encoding='utf8')
        self.prefs={'likes':'鱼','avoid':'香菜','taste':'清淡','notes':''}
        self.cog.diet_preferences_provider=lambda:dict(self.prefs)
        self.ref='routine:2026-09-28:lunch'
        self.item={'id':'lunch','state_type':'eating','kind':'meal','activity':'lunch','reference_id':self.ref,
                   'place':'home.f1.dining','start_at':self.clock.now().isoformat(),
                   'end_at':(self.clock.now()+timedelta(hours=1)).isoformat()}
        self.cog.agenda.view=Mock(side_effect=lambda *a,**kw:{'current_item':deepcopy(self.item)})
        self.cog.agenda.read=Mock(side_effect=lambda *a,**kw:{'revision':1,'items':[deepcopy(self.item)]})
        self.cog.agenda._read=Mock(side_effect=lambda *a,**kw:{'revision':1,'items':[deepcopy(self.item)]})

    def command(self,ident,op,**args): return self.p.command(ident,self.p.snapshot()['revision'],op,**args)

    def ticks(self,seconds):
        while seconds>0:
            part=min(60,seconds); self.clock.advance(part);meal_skill.heartbeat(self.cog);seconds-=part

    def test_dining_places_install_is_persistent_reachable_and_idempotent(self):
        from life_prototype import meal_places
        before=self.p.snapshot()
        self.assertTrue(meal_places.install(self.cog))
        self.assertEqual(self.p.snapshot()['place'],before['place'])
        self.assertIn('city.dining_access',self.p.config['places'])
        self.assertEqual(meal_skill.travel(self.p.config,'home.f1.kitchen','test.restaurant'),0)
        revision=self.p.snapshot()['revision']
        self.assertTrue(meal_places.install(self.cog))
        self.assertEqual(self.p.snapshot()['revision'],revision)
        with self.cog.store.connect() as db:
            record=json.loads(db.execute("SELECT body FROM life_state WHERE name='work_extension'").fetchone()[0])
        self.assertEqual(record['config'],self.p.config)

    def test_home_only_cooking_or_takeout_and_live_preferences(self):
        choices=meal_skill.options(self.cog,self.item,self.p.snapshot(),self.clock.now())
        self.assertEqual({r['mode'] for r in choices},{'cook','takeout'})
        result=meal_skill.prepare(self.cog)
        self.assertFalse(result['meal']['ready'])
        self.assertEqual(self.model.calls[0][1]['user_preferences'],self.prefs)
        self.prefs['likes']='面食'
        self.assertEqual(meal_skill.preferences(self.cog)['likes'],'面食')
        meal_skill.prepare(self.cog)
        self.assertEqual(len(self.model.calls),1)

    def test_breakfast_uses_breakfast_menu_and_rejects_lunch_style_food(self):
        self.item.update(id='breakfast', activity='breakfast', reference_id='routine:2026-09-28:breakfast')
        self.ref=self.item['reference_id']
        plan=meal_skill.prepare(self.cog)['meal']
        self.assertEqual(plan['dishes'], ['燕麦粥','煎蛋','咖啡'])
        with self.assertRaises(ValueError):
            meal_skill.validate_meal_period('breakfast', ['米饭','糖醋排骨','清炒西兰花'])

    def test_outside_uses_named_restaurant_not_takeout_or_cooking(self):
        self.item['place']='test.restaurant'
        choices=meal_skill.options(self.cog,self.item,self.p.snapshot(),self.clock.now())
        self.assertTrue(choices)
        self.assertEqual({r['mode'] for r in choices},{'dine'})
        self.assertTrue(all(r['place']=='test.restaurant' for r in choices))
        self.model.mode='dine'
        plan=meal_skill.prepare(self.cog)['meal']
        self.assertEqual(plan['place'],'test.restaurant')
        self.assertEqual(plan['menu_basis'],'inferred_from_venue_name_or_home_cooking')

    def test_office_defaults_to_packed_meal_heating_then_eating(self):
        self.item['place']='firm.office';self.model.mode='packed'
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['place']='firm.office'
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(json.dumps(state),))
        choices=meal_skill.options(self.cog,self.item,self.p.snapshot(),self.clock.now())
        self.assertEqual({(r['mode'],r['place']) for r in choices},{('packed','firm.office')})
        plan=meal_skill.prepare(self.cog)['meal']
        self.command('heat','start',activity_id='heat',kind='cooking',target=self.ref)
        self.assertIn('加热自带',self.p.snapshot()['activities']['heat']['description'])
        self.ticks(plan['prepare_seconds'])
        self.assertEqual(self.p.snapshot()['meals'][self.ref]['remaining'],1)
        self.command('eat','start',activity_id='eat',kind='eating',target=self.ref)
        self.ticks(plan['eat_seconds']);self.cog.ingest()
        self.assertIn('completed_at',self.p.snapshot()['meal_plans'][self.ref])
        with self.p.store.connect() as db:
            descriptions=[r[0] for r in db.execute("SELECT description FROM events WHERE kind='meal_completed'")]
        self.assertTrue(any('热好了自带的' in row for row in descriptions))

    def test_unknown_external_place_does_not_choose_another_restaurant(self):
        self.item['place']='unknown.external'
        self.assertEqual(meal_skill.options(self.cog,self.item,self.p.snapshot(),self.clock.now()),[])

    def test_cook_is_not_eating_and_resume_does_not_credit_offline_gap(self):
        plan=meal_skill.prepare(self.cog)['meal']
        self.command('cook','start',activity_id='cook',kind='cooking',target=self.ref)
        self.ticks(60)
        self.command('pause','interrupt',activity_id='cook',reason='message')
        self.clock.advance(120)
        self.command('resume','resume',activity_id='cook')
        self.assertEqual(self.p.snapshot()['activities']['cook']['progress'],60)
        self.ticks(plan['prepare_seconds']-60)
        state=self.p.snapshot()
        self.assertTrue(state['meal_plans'][self.ref]['ready'])
        self.assertEqual(state['meals'][self.ref]['remaining'],1)
        self.assertNotIn('completed_at',state['meal_plans'][self.ref])
        self.assertEqual(progress_view(state['activities']['cook'],self.p.config)['progress_unit'],'simulated_meal_seconds')
        from life_prototype.coarse_plan_execution import requirement
        self.assertEqual(requirement(self.cog)['kind'],'serving')

    def test_takeout_and_eating_complete_separately_without_duplicate_events(self):
        self.model.mode='takeout'
        # Place the isolated fixture at the dining table before its decision.
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['place']='home.f1.dining'
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(json.dumps(state),))
        plan=meal_skill.prepare(self.cog)['meal']
        self.command('order','start',activity_id='wait',kind='cooking',target=self.ref)
        self.ticks(plan['prepare_seconds'])
        self.command('eat','start',activity_id='eat',kind='eating',target=self.ref)
        self.ticks(plan['eat_seconds'])
        self.assertFalse(meal_skill.heartbeat(self.cog))
        self.cog.ingest();self.cog.ingest()
        state=self.p.snapshot()
        self.assertEqual(state['meals'][self.ref]['remaining'],0)
        self.assertIn('eaten_at',state['meal_plans'][self.ref])
        self.assertNotIn('completed_at',state['meal_plans'][self.ref])
        with self.p.store.connect() as db:
            events=[r[0] for r in db.execute("SELECT description FROM events WHERE kind='meal_completed'")]
            self.assertEqual(len(events),2)
            self.assertTrue(any('收到了外卖' in r for r in events))
            self.assertTrue(any('吃完了清蒸鱼' in r for r in events))

    def test_cannot_eat_unprepared_food_or_accept_spicy_plan(self):
        self.model.spicy=True
        with self.assertRaises(ValueError): meal_skill.prepare(self.cog)
        self.assertNotIn(self.ref,self.p.snapshot().get('meal_plans',{}))
        self.model.spicy=False
        meal_skill.prepare(self.cog)
        with self.assertRaises(ValueError): self.command('bad','start',activity_id='bad',kind='eating',target=self.ref)

    def test_coarse_slot_boundary_caps_preparation_and_creates_no_completion(self):
        meal_skill.prepare(self.cog)
        self.command('cook','start',activity_id='cook',kind='cooking',target=self.ref)
        with self.p.store.connect() as db:
            state=self.p.store.read(db)
            state['meal_plans'][self.ref]['end_at']=(self.clock.now()+timedelta(seconds=20)).isoformat()
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(json.dumps(state),))
        self.clock.advance(60)
        self.command('stop','interrupt',activity_id='cook',reason='coarse boundary')
        self.assertEqual(self.p.snapshot()['activities']['cook']['progress'],20)
        self.assertFalse(self.p.snapshot()['meal_plans'][self.ref]['ready'])

    def test_life_agent_can_execute_saved_meal_without_recipe_inventory(self):
        from life_prototype.scheduler import Scheduler
        from life_prototype.autonomous_agent import LifeAgent
        _,_,_,scheduler_config=configurations()
        scheduler=Scheduler(self.chat,scheduler_config)
        agent=LifeAgent(scheduler)
        meal_skill.prepare(self.cog)
        result=agent._action('meal-start',{'expected_revision':self.p.snapshot()['revision'],
            'action':{'operation':'start','activity_id':None,'kind':'cooking','target':self.ref},'movement_purpose':None})
        self.assertTrue(result['active_activity'])
        self.assertEqual(self.p.snapshot()['activities'][result['active_activity']]['meal_phase'],'cook')

    def test_cooked_food_is_carried_to_dining_before_eating(self):
        from life_prototype.home_world import checkpoint
        from life_prototype.clock import utc
        plan=meal_skill.prepare(self.cog)['meal']
        self.command('cook','start',activity_id='cook',kind='cooking',target=self.ref)
        self.ticks(plan['prepare_seconds'])
        from life_prototype.coarse_locations import advance
        advance(self.cog)
        self.assertEqual(self.p.snapshot()['meals'][self.ref]['place'],'home.f1.dining')
        self.command('eat','start',activity_id='eat',kind='eating',target=self.ref)
        self.ticks(plan['eat_seconds'])
        self.assertEqual(self.p.snapshot()['meals'][self.ref]['remaining'],0)

    def test_completed_meal_observation_has_verified_need_update_basis(self):
        from life_prototype.event_assimilation import control_event_evidence
        self.model.mode='takeout'
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['place']='home.f1.dining'
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(json.dumps(state),))
        plan=meal_skill.prepare(self.cog)['meal']
        self.command('prep','start',activity_id='prep',kind='cooking',target=self.ref)
        self.ticks(plan['prepare_seconds'])
        self.command('eat','start',activity_id='eat',kind='eating',target=self.ref)
        self.ticks(plan['eat_seconds']);self.cog.ingest()
        with self.p.store.connect() as db:
            observation=json.loads(db.execute("SELECT body FROM life_observations WHERE id='obs:meal-finished:eat'").fetchone()[0])
            fact=control_event_evidence(self.p,db,observation)
            self.assertEqual(fact['actual_result']['portion'],1)
            self.assertNotIn('allowed_dimensions',observation)
            self.assertNotIn('needs',self.p.snapshot())
            observation['fact']['actual_result']['portion']=2
            with self.assertRaises(ValueError):control_event_evidence(self.p,db,observation)


class DietPreferencesTests(unittest.TestCase):
    def test_personalization_api_preserves_profile_for_old_clients_and_allows_clearing(self):
        import ast
        from datetime import datetime
        from fastapi import HTTPException
        source=Path(__file__).resolve().parents[1]/'app/runtime.py'
        tree=ast.parse(source.read_text(encoding='utf8'))
        functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in
                   {'get_personalization_settings','set_personalization_settings'}]
        for function in functions:function.decorator_list=[]
        settings={}
        ns={'PersonalizationSettingRequest':PersonalizationSettingRequest,'datetime':datetime,'HTTPException':HTTPException,
            'get_app_setting':lambda key,default='':settings.get(key,default),'set_app_setting':settings.__setitem__}
        exec(compile(ast.Module(body=functions,type_ignores=[]),str(source),'exec'),ns)
        data=dict(libra_name='左然',user_name='我',libra_nickname='左然',user_nickname='我',user_address='你',
                  met_at='2026-04-26',checkin_min_minutes=10,checkin_max_minutes=20,
                  weather_reminder_enabled=True,state_update_enabled=True)
        ns['set_personalization_settings'](PersonalizationSettingRequest(**data,user_diet_preferences={'likes':'面食','avoid':'花生'}))
        ns['set_personalization_settings'](PersonalizationSettingRequest(**data))
        self.assertEqual(ns['get_personalization_settings']()['user_diet_preferences']['avoid'],'花生')
        ns['set_personalization_settings'](PersonalizationSettingRequest(**data,user_diet_preferences={}))
        self.assertEqual(ns['get_personalization_settings']()['user_diet_preferences'],normalize({}))

    def test_preferences_roundtrip_clear_and_unknown_are_explicit(self):
        settings={}
        getter=lambda key,default:settings.get(key,default)
        self.assertEqual(read(getter),normalize({}))
        save({'likes':'  面食  ','avoid':'花生'},settings.__setitem__)
        self.assertEqual(read(getter)['likes'],'面食')
        save({},settings.__setitem__)
        self.assertEqual(read(getter)['avoid'],'')
        with self.assertRaises(ValueError): save({'likes':'a'*501},settings.__setitem__)

    def test_older_clients_omit_diet_field_without_defaulting_to_empty_profile(self):
        request=PersonalizationSettingRequest(libra_name='左然',user_name='我',libra_nickname='左然',user_nickname='我',
            user_address='你',met_at='2026-04-26',checkin_min_minutes=10,checkin_max_minutes=20,
            weather_reminder_enabled=True,state_update_enabled=True)
        self.assertIsNone(request.user_diet_preferences)


if __name__=='__main__':unittest.main()
