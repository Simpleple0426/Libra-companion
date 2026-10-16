"""Durable laundry dependencies and bounded interruptions of optional home time."""
from copy import deepcopy
from datetime import timedelta
import json

from .clock import utc
from .config import canonical, digest
from .coarse_plan import schedule_day
from .coarse_plan_schema import pack
from .skill_housework import steps_for, routine, enabled
from .skill_dining import travel

PAUSE_AFTER_SECONDS=300
TRANSITION_BUFFER_SECONDS=180


def refresh(cog):
    """Derive durable tasks from committed batch states, even while asleep."""
    now=cog.clock.now()
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE');state=cog.store.read(db)
        before=deepcopy(state.get('household_followups',{}))
        tasks=state.setdefault('household_followups',{})
        for batch in state.get('laundry_batches',{}).values():
            phases=['hang']+(['store'] if batch['status'] in {'airing','dry','carrying_dry','stored'} else [])
            for phase in phases:
                ident='laundry-followup:'+batch['id']+':'+phase
                task=tasks.setdefault(ident,{'id':ident,'batch_id':batch['id'],'phase':phase,
                    'title':'晾晒洗好的衣物' if phase=='hang' else '收衣并叠放',
                    'created_at':now.isoformat(),'status':'waiting','source':'committed_laundry_dependency'})
                complete=(batch['status'] in {'airing','dry','carrying_dry','stored'}) if phase=='hang' else batch['status']=='stored'
                ready=batch['status'] in ({'washed','carrying_wet'} if phase=='hang' else {'dry','carrying_dry'})
                task['status']='completed' if complete else 'ready' if ready else 'waiting'
                if complete: task.setdefault('completed_at',now.isoformat())
                if ready: task.setdefault('ready_at',now.isoformat())
                if task['status']=='waiting':
                    machine=state.get('household_machines',{}).get(batch.get('machine_id'),{})
                    task['dependency']='washing_completed' if phase=='hang' else 'air_drying_completed'
                    task['expected_ready_at']=machine.get('finishes_at') if phase=='hang' else batch.get('dry_at')
        if tasks==before: return False
        state['revision']+=1
        db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
    return True


def soft_slot(item):
    from .skill_personal_care import routine as care_routine
    constraints=item.get('constraints',{})
    return (item.get('state_type') in {'free','resting'} and str(item.get('place','')).startswith('home.')
        and item.get('kind') not in {'commute','bedtime','meal','shower','interaction'}
        and not item.get('appointment_id') and not item.get('source_message')
        and not constraints.get('appointment_id') and not constraints.get('source_message')
        and not constraints.get('required_routine') and not constraints.get('household_followup_id')
        and item.get('activity') not in {'working','work','home_work','user_time','prepare_meal'}
        and item.get('intent') not in {'工作','备餐','陪伴交流','运动'}
        and not routine(item) and not care_routine(item))


def _resume_fine(db,cog,active,parent,agenda_revision,now):
    """Carry the exact interrupted book/movie choice into the return slot."""
    binding=db.execute('SELECT block_id FROM life_fine_execution WHERE activity_id=?',(active['id'],)).fetchone()
    if not binding: return
    rows=db.execute("SELECT body FROM life_fine_agendas WHERE status='ready'").fetchall()
    found=next(((json.loads(r[0]),b) for r in rows for b in json.loads(r[0])['blocks'] if b['id']==binding[0]),None)
    if not found: return
    original,old=found
    ident='fine:household-resume:'+digest([active['id'],parent['id']])[:24]
    start,end=utc(parent['start_at']),utc(parent['end_at'])
    block={**deepcopy(old),'id':ident+':0','start_at':start.isoformat(),'end_at':end.isoformat(),
           'duration_seconds':int((end-start).total_seconds()),'baseline':active['progress'],
           'execution_started_at':start.isoformat(),'budget_used_seconds':0}
    block.pop('schedule_status',None)
    if active['kind']=='reading':
        from .skill_reading import plan as reading_plan
        block['reading_plan']=reading_plan(cog.p.config['books'][active['target']],active['progress'],block['duration_seconds'],cog.p.config)
    body={'id':ident,'parent_id':parent['id'],'agenda_revision':agenda_revision,'created_at':now.isoformat(),
          'parent':deepcopy(parent),'parent_title':parent['title'],'blocks':[block],
          'reason':'continue_exact_resource_after_household_followup','resource_hash':original.get('resource_hash','')}
    db.execute('INSERT INTO life_fine_agendas VALUES(?,?,?,?,?)',(ident,parent['id'],'ready',1,canonical(body)))
    db.execute('UPDATE life_fine_execution SET block_id=?,parent_id=?,end_at=? WHERE activity_id=?',
               (block['id'],parent['id'],end.isoformat(),active['id']))


def schedule_ready(cog):
    """Borrow only the current eligible slot; later slots are reconsidered when due.

    Never preempt work, sleep, messages, appointments or a current machine/human chore.
    A day with no eligible slot leaves a visible pending task, not a fabricated result.
    """
    if not enabled(cog): return False
    now=cog.clock.now()
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE');state=cog.store.read(db)
        if state.get('sleep',{}).get('status')!='awake' or not str(state['place']).startswith('home.'): return False
        if db.execute("SELECT 1 FROM result_controls WHERE status='pending' LIMIT 1").fetchone(): return False
        if db.execute("SELECT 1 FROM life_agenda_messages WHERE status IN ('pending','running') LIMIT 1").fetchone(): return False
        agenda=cog.agenda._read(db,schedule_day(now))
        if not agenda: return False
        item=next((i for i in agenda['items'] if utc(i['start_at'])<=now<utc(i['end_at'])),None)
        if not item or not soft_slot(item): return False
        active=state['activities'].get(state.get('active'))
        if active:
            if active['kind'] not in {'reading','watching'}: return False
            if (now-utc(active.get('resumed_at',active['started_at']))).total_seconds()<PAUSE_AFTER_SECONDS: return False
            if active['place']!=item['place']: return False
            # A bound choice is required to resume the same content reliably.
            if not db.execute('SELECT 1 FROM life_fine_execution WHERE activity_id=?',(active['id'],)).fetchone(): return False
        tasks=sorted((t for t in state.get('household_followups',{}).values() if t['status']=='ready'),
                     key=lambda t:(t.get('ready_at',t['created_at']),t['id']))
        for task in tasks:
            if any(c.get('source',[])[:2]==['household_followup',task['id']]
                   for c in agenda.get('user_constraints',{}).get('cancelled',[])): continue
            if any(i.get('constraints',{}).get('household_followup_id')==task['id'] and utc(i['end_at'])>now for i in agenda['items']): continue
            chore_name='dry_laundry' if task['phase']=='hang' else 'fold_laundry'
            constraints={'housework_routine':chore_name,'household_followup_id':task['id'],'laundry_batch_id':task['batch_id']}
            probe={'activity':chore_name,'place':item['place'],'state_type':'free','constraints':constraints}
            steps,reason=steps_for(cog.p.config,state,probe)
            if not steps: continue
            origin=state['place'];seconds=TRANSITION_BUFFER_SECONDS
            try:
                for step in steps:
                    seconds+=travel(cog.p.config,origin,step['place'])+step['seconds']-step['progress'];origin=step['place']
                return_seconds=travel(cog.p.config,origin,item['place'])
            except (ValueError,KeyError): continue
            chore_end=now+timedelta(seconds=seconds)
            return_end=chore_end+timedelta(seconds=return_seconds)
            # Keep a real continuation window and never change a later appointment.
            if return_end+timedelta(seconds=max(60,cog.p.config['checkpoint_seconds']))>utc(item['end_at']): continue
            reservations=agenda.get('user_constraints',{}).get('appointments',[])
            if any(utc(a['start_at'])<return_end and utc(a['end_at'])>now for a in reservations): continue
            if any(c.get('status')=='confirmed' and now<=utc(c['due_at'])<=return_end for c in state.get('commitments',[])): continue
            revision=agenda['revision']+1;token=digest([task['id'],item['id'],revision])[:20]
            if active:
                cog.p._commit_locked(db,'household-pause:'+token,{'operation':'interrupt',
                    'expected_revision':state['revision'],'payload':{'activity_id':active['id'],'reason':'洗衣后续任务：短暂处理后继续原活动'}},None)
                state=cog.store.read(db);active=state['activities'][active['id']]
                task=state['household_followups'][task['id']]
                if active['status']!='interrupted': active=None
            body=deepcopy(agenda);new=[]
            for row in body['items']:
                if row['id']!=item['id']: new.append(row);continue
                if utc(row['start_at'])<now:
                    head=deepcopy(row);head['end_at']=now.isoformat();head['end_time']=now.isoformat();new.append(head)
                chores={'id':'household-slot:'+token,'kind':'free','state_type':'free','intent':'家务',
                    'activity':chore_name,'title':task['title'],'place':steps[0]['place'],
                    'place_name':cog.p.config['places'][steps[0]['place']]['name'],
                    'start_at':now.isoformat(),'end_at':chore_end.isoformat(),'constraints':constraints,
                    'source_window':['household_followup',task['id'],now.isoformat(),chore_end.isoformat()]}
                new.append(chores)
                if return_seconds:
                    new.append({'id':'household-return:'+token,'kind':'commute','state_type':'commuting','activity':'moving',
                        'title':'返回'+item.get('place_name',item['place']),'place':origin,'place_name':cog.p.config['places'][origin]['name'],
                        'destination':item['place'],'destination_name':item.get('place_name',item['place']),
                        'start_at':chore_end.isoformat(),'end_at':return_end.isoformat(),
                        'constraints':{'household_return_for':task['id']}})
                tail=deepcopy(row);tail.update(id='household-resume:'+token,start_at=return_end.isoformat(),start_time=return_end.isoformat())
                tail.setdefault('constraints',{})['household_resume_after']=task['id']
                if active: tail['constraints']['resume_activity_id']=active['id']
                new.append(tail)
            body.update(items=new,revision=revision,change_reason='laundry_followup_inserted',
                        evidence_id=f"agenda:{agenda['date']}:r{revision}")
            task.update(scheduled_item_id=chores['id'],scheduled_revision=revision,scheduled_at=now.isoformat(),
                        resume_item_id=tail['id'],attempts=task.get('attempts',0)+1)
            if active: _resume_fine(db,cog,active,tail,revision,now)
            state['revision']+=1
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
            db.execute('INSERT INTO life_daily_agendas VALUES(?,?,?)',(agenda['date'],revision,canonical(pack(body))))
            return True
    return False
