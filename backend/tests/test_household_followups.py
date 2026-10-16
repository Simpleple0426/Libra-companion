from copy import deepcopy
from datetime import timedelta
import json
import unittest
from unittest.mock import patch
import test_housework_skill as fixture

from life_prototype import household_followups as followups, skill_housework as housework_skill
from life_prototype.coarse_plan_schema import pack
from life_prototype.clock import utc
from life_prototype.config import canonical
from life_prototype.coarse_plan import schedule_day
from life_prototype.fine_plan import initialize,view,reconcile
from life_prototype.coarse_plan_execution import requirement


class FollowupTests(unittest.TestCase):
    command=fixture.HouseworkTests.command
    set_place=fixture.HouseworkTests.set_place
    ticks=fixture.HouseworkTests.ticks
    execute_plan=fixture.HouseworkTests.execute_plan

    def setUp(self):
        fixture.HouseworkTests.setUp(self)
        for key in ('read','_read','view'): delattr(self.cog.agenda,key)
        initialize(self.cog.store)
        self.set_place('home.f2.media')
        self.parent={'id':'leisure','kind':'free','state_type':'free','activity':'watch_movie','intent':'看电影',
            'title':'看电影','place':'home.f2.media','place_name':'影音区',
            'start_at':self.clock.now().isoformat(),'end_at':(self.clock.now()+timedelta(hours=2)).isoformat()}
        self.save_agenda([self.parent])
        self.batch('washed')

    def save_agenda(self,items,appointments=None):
        old=self.cog.agenda.read();revision=old['revision']+1 if old else 1
        body={'date':str(schedule_day(self.clock.now())),'revision':revision,'basis':'fixture',
            'evidence_id':'agenda-fixture:'+str(revision),'items':deepcopy(items),'commitments':[],
            'calendar':{'day_type':'rest_day'},'user_constraints':{'appointments':appointments or [],'cancelled':[]}}
        with self.p.store.connect() as db:
            db.execute('INSERT INTO life_daily_agendas VALUES(?,?,?)',(body['date'],revision,canonical(pack(body))))

    def batch(self,status,ident='batch'):
        with self.p.store.connect() as db:
            state=self.p.store.read(db)
            state.setdefault('laundry_batches',{})[ident]={'id':ident,'machine_id':ident,'status':status,'place':'home.f2.bathroom','dry_at':(self.clock.now()+timedelta(hours=4)).isoformat()}
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
        followups.refresh(self.cog)

    def start_movie(self,kind='watching'):
        from life_prototype.resource_library import library
        self.movie='movie:about_time';self.p.config['movies']=library(movie_place='home.f2.media')['movies']
        if kind=='reading':
            from life_prototype.skill_reading import imported_book
            folder=self.root/'book';folder.mkdir();(folder/'a.txt').write_text('fixture',encoding='utf8')
            self.movie,book=imported_book(folder,{'bookId':'fixture','title':'Book','sourceHash':'v1',
                'chunks':[{'id':'a','path':'a.txt','charCount':100000,'sectionTitle':'Chapter'}]})
            self.p.config['books'][self.movie]=book
            self.p.config['objects'][book['object']]={'name':'Book','parent':'home.f2.study','status':'confirmed','source':'fixture'}
            self.parent.update(place='home.f2.study',place_name='书房',activity='reading',intent='阅读')
            self.set_place('home.f2.study');self.save_agenda([self.parent])
        now=self.clock.now();block={'id':'fine0:0','kind':kind,'target':self.movie,'place':self.parent['place'],
            'place_name':'影音区','title':'电影','start_at':now.isoformat(),'end_at':self.parent['end_at'],
            'duration_seconds':7200,'baseline':0,'rewatch':False}
        body={'id':'fine0','parent_id':'leisure','agenda_revision':self.cog.agenda.read()['revision'],
            'parent':deepcopy(self.parent),'created_at':now.isoformat(),'parent_title':'电影','blocks':[block],'resource_hash':'fixture','reason':'fixture'}
        with self.p.store.connect() as db:
            db.execute('INSERT INTO life_fine_agendas VALUES(?,?,?,?,?)',('fine0','leisure','ready',1,canonical(body)))
        self.command('movie-start','start',activity_id='movie',kind=kind,target=self.movie)
        with self.p.store.connect() as db:
            db.execute('INSERT INTO life_fine_execution VALUES(?,?,?,?)',('movie','fine0:0','leisure',self.parent['end_at']))
        if kind=='watching': from life_prototype.skill_movie import heartbeat
        else: from life_prototype.skill_reading import heartbeat
        for _ in range(5): self.clock.advance(60);heartbeat(self.cog)

    def test_dependency_queue_waits_for_actual_washing_then_ready(self):
        self.batch('washing')
        task=next(iter(self.p.snapshot()['household_followups'].values()))
        self.assertEqual(task['status'],'waiting');self.assertFalse(followups.schedule_ready(self.cog))
        self.batch('washed')
        self.assertTrue(followups.schedule_ready(self.cog))
        self.assertFalse(followups.schedule_ready(self.cog))
        self.assertEqual(len([i for i in self.cog.agenda.read()['items'] if i.get('constraints',{}).get('household_followup_id')]),1)

    def test_insert_chore_and_return_without_changing_future_appointment(self):
        appointment={'id':'user','state_type':'free','kind':'interaction','activity':'user_time','title':'陪用户聊天',
            'place':'home.f2.media','place_name':'影音区','start_at':self.parent['end_at'],
            'end_at':(utc(self.parent['end_at'])+timedelta(minutes=30)).isoformat(),'appointment_id':'user-appointment'}
        self.save_agenda([self.parent,appointment]);before=self.cog.agenda.read()['items'][-1]
        self.assertTrue(followups.schedule_ready(self.cog))
        items=self.cog.agenda.read()['items']
        self.assertEqual(items[-1],before)
        self.assertFalse(any(i['kind']=='commute' for i in items))
        self.assertTrue(any(i.get('constraints',{}).get('household_resume_after') for i in items))
        self.assertTrue(all(utc(a['end_at'])<=utc(b['start_at']) for a,b in zip(items,items[1:])))

    def test_movie_pause_chore_return_and_resume_exact_progress(self):
        self.start_movie();progress=self.p.snapshot()['activities']['movie']['progress']
        self.assertTrue(followups.schedule_ready(self.cog))
        self.assertEqual(self.p.snapshot()['activities']['movie']['status'],'interrupted')
        self.assertEqual(self.p.snapshot()['activities']['movie']['progress'],progress)
        plan=housework_skill.prepare(self.cog)['housework'];self.execute_plan(plan)
        followups.refresh(self.cog)
        task=next(t for t in self.p.snapshot()['household_followups'].values() if t['phase']=='hang')
        self.assertEqual(task['status'],'completed')
        tail=next(i for i in self.cog.agenda.read()['items'] if i.get('constraints',{}).get('resume_activity_id'))
        self.clock.advance(max(0,(utc(tail['start_at'])-self.clock.now()).total_seconds()))
        from life_prototype.coarse_locations import advance
        advance(self.cog)
        self.assertEqual(self.p.snapshot()['place'],tail['place'])
        reconcile(self.cog)
        self.assertEqual(view(self.cog)['current_item']['target'],self.movie)
        self.assertEqual(requirement(self.cog)['targets'],[self.movie])
        from life_prototype.scheduler import Scheduler,DEFAULTS
        from life_prototype.autonomous_agent import LifeAgent
        agent=LifeAgent(Scheduler(self.chat,DEFAULTS))
        with patch.object(self.cog,'_decision_ready',return_value=None):
            agent._action('resume-movie',{'expected_revision':self.p.snapshot()['revision'],
                'action':{'operation':'resume','activity_id':'movie','kind':'watching','target':self.movie},'movement_purpose':None})
        self.assertEqual(self.p.snapshot()['activities']['movie']['progress'],progress)
        self.assertEqual(self.p.snapshot()['active'],'movie')

    def test_reading_choice_and_chapter_progress_survive_interruption(self):
        self.start_movie('reading');before=self.p.snapshot()['activities']['movie']['progress']
        self.assertTrue(followups.schedule_ready(self.cog))
        tail=next(i for i in self.cog.agenda.read()['items'] if i.get('constraints',{}).get('resume_activity_id'))
        self.clock.advance((utc(tail['start_at'])-self.clock.now()).total_seconds());reconcile(self.cog)
        block=view(self.cog)['current_item']
        self.assertEqual(block['target'],self.movie);self.assertEqual(block['baseline'],before)
        self.assertIn('reading_plan',block)
        self.assertEqual(self.p.snapshot()['activities']['movie']['progress'],before)

    def test_explicit_user_cancellation_is_not_silently_undone(self):
        self.assertTrue(followups.schedule_ready(self.cog))
        agenda=self.cog.agenda.read();chore=next(i for i in agenda['items'] if i.get('constraints',{}).get('household_followup_id'))
        agenda.update(items=[self.parent],revision=agenda['revision']+1)
        agenda['user_constraints']['cancelled']=[{'source':chore['source_window'],'from':chore['start_at'],'until':chore['end_at']}]
        with self.p.store.connect() as db:
            db.execute('INSERT INTO life_daily_agendas VALUES(?,?,?)',(agenda['date'],agenda['revision'],canonical(pack(agenda))))
        self.assertFalse(followups.schedule_ready(self.cog))

    def test_work_sleep_outside_and_user_time_are_not_preempted(self):
        original=deepcopy(self.parent)
        for changes in ({'state_type':'working','activity':'working'},
                        {'activity':'user_time','appointment_id':'user'},
                        {'place':'firm.office'}, {'activity':'bedtime_preparation'}):
            with self.subTest(changes=changes):
                self.save_agenda([{**original,**changes}]);self.assertFalse(followups.schedule_ready(self.cog))
        self.save_agenda([original])
        with self.p.store.connect() as db:
            state=self.p.store.read(db);state['sleep']['status']='sleeping'
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
        self.assertFalse(followups.schedule_ready(self.cog))

    def test_short_slot_defers_until_later_eligible_slot(self):
        short={**self.parent,'end_at':(self.clock.now()+timedelta(minutes=2)).isoformat()}
        later={**self.parent,'id':'later','start_at':short['end_at']}
        self.save_agenda([short,later]);self.assertFalse(followups.schedule_ready(self.cog))
        self.clock.advance(120);self.assertTrue(followups.schedule_ready(self.cog))

    def test_user_reservation_and_pending_message_take_priority(self):
        appointment={'id':'user','start_at':self.clock.now().isoformat(),'end_at':(self.clock.now()+timedelta(minutes=30)).isoformat()}
        self.save_agenda([self.parent],[appointment]);self.assertFalse(followups.schedule_ready(self.cog))
        self.save_agenda([self.parent])
        with self.p.store.connect() as db: db.execute("INSERT INTO life_agenda_messages(message_id,status) VALUES('user','pending')")
        self.assertFalse(followups.schedule_ready(self.cog))

    def test_airing_creates_store_dependency_and_dry_makes_it_ready(self):
        self.batch('airing')
        tasks=self.p.snapshot()['household_followups']
        self.assertEqual(next(t for t in tasks.values() if t['phase']=='hang')['status'],'completed')
        self.assertEqual(next(t for t in tasks.values() if t['phase']=='store')['status'],'waiting')
        self.assertFalse(followups.schedule_ready(self.cog));self.batch('dry')
        self.assertTrue(followups.schedule_ready(self.cog))
        self.assertEqual(self.cog.agenda.view()['current_item']['activity'],'fold_laundry')

    def test_revoked_slot_is_rescheduled_without_duplicate_laundry(self):
        self.assertTrue(followups.schedule_ready(self.cog))
        self.save_agenda([self.parent])
        self.assertTrue(followups.schedule_ready(self.cog))
        self.assertEqual(len(self.p.snapshot()['household_followups']),1)
        self.assertEqual(next(iter(self.p.snapshot()['household_followups'].values()))['attempts'],2)

    def test_followup_selects_its_batch_not_another_ready_batch(self):
        self.batch('washed','second');tasks=self.p.snapshot()['household_followups']
        with self.p.store.connect() as db:
            state=self.p.store.read(db)
            task=next(t for t in state['household_followups'].values() if t['batch_id']=='second')
            task['ready_at']=(self.clock.now()-timedelta(hours=1)).isoformat()
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
        self.assertTrue(followups.schedule_ready(self.cog));plan=housework_skill.prepare(self.cog)['housework']
        effects=[self.p.snapshot()['housework_steps'][key]['effect'] for key in plan['step_ids']]
        self.assertTrue(all(e['batch']=='second' for e in effects))


if __name__=='__main__': unittest.main()
