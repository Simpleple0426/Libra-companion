"""Lightweight work phases: no legal prose, case outcomes or offline work."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from application.content_tools import execute
from .skill_personal_care import enabled
from .clock import utc
from .config import canonical,digest
from .activity_engine import require
from .daily_obligations import descendant

LABELS={'materials':'查阅案件材料','research':'查阅相关资料','contract':'审阅合同','notes':'整理工作笔记',
        'discussion':'与同事讨论工作','zhai':'与翟星讨论工作','client':'与委托人沟通',
        'break':'在茶水间接水、稍作休息','field':'处理外勤事务','institution':'处理工作事务'}


def routine(item):
    return bool(item and item.get('state_type') not in {'commuting','sleeping','eating'} and
                (item.get('state_type')=='working' or item.get('intent')=='工作' or item.get('activity') in {'working','work','home_work'}))


def category(config,place):
    if descendant(config,place,'firm'):return 'office'
    if descendant(config,place,'home'):return 'home'
    name=config['places'][place]['name']
    if '法院' in name or '检察院' in name:return 'institution'
    if '警' in name:return 'field'
    return 'client'


def plan_for(config,state,item,now):
    ident='workday:'+item['id'];place=item['place'];mode=category(config,place)
    budget=max(1,int((utc(item['end_at'])-now).total_seconds()))
    seed=int(digest(item['id'])[:8],16)
    desk='firm.office' if mode=='office' else place
    previous=state.get('work_continuation',{})
    task=previous.get('task') if previous.get('mode')==mode else None
    task=task if task in {'materials','research','contract','notes'} else ('materials','research','contract')[seed%3]
    sequence=[(task,desk)]
    if mode in {'institution','field','client'}:sequence=[(mode,place)]
    elif budget>=5400:
        if mode=='office' and seed%4==0:
            sequence=[('discussion','firm.open_office'),('research',desk)]
        elif mode=='office' and seed%4==1:
            sequence=[('zhai','firm.zhai_office'),('research',desk)]
        elif mode=='office' and seed%4==2:
            sequence=[('client',('firm.reception','firm.office','firm.consultation')[(seed//4)%3]),(task,desk)]
        if mode=='office' and seed%2==0:sequence += [('break','firm.pantry'),(sequence[-1][0],desk)]
        sequence += [('notes',desk)]
    elif budget>=2700:sequence += [('notes',desk)]
    # Reserve actual route time, rather than filling the whole slot with work.
    from .skill_dining import travel
    origin=state['place'];moving=0
    for _,room in sequence:
        moving+=travel(config,origin,room);origin=room
    usable=max(1,budget-moving)
    pause=300 if any(t=='break' for t,_ in sequence) else 0
    count=sum(t!='break' for t,_ in sequence);share=max(1,(usable-pause)//count)
    steps=[]
    for i,(kind,room) in enumerate(sequence):
        seconds=pause if kind=='break' else share
        steps.append({'id':ident+':'+str(i),'plan_id':ident,'task':kind,'title':LABELS[kind],
            'place':room,'seconds':seconds,'progress':0,'continues':
            (i==0 and previous.get('task')==kind and previous.get('mode')==mode) or
            (i>0 and sequence[i-1][0]=='break')})
    return {'id':ident,'parent_id':item['id'],'coarse_place':place,'mode':mode,'end_at':item['end_at'],
            'cursor':0,'step_ids':[s['id'] for s in steps],'created_at':now.isoformat()},steps


def requirement(cog,state,item,result,at):
    plan=state.get('work_sessions',{}).get('workday:'+item['id'])
    if not plan:return {**result,'mode':'needs_detail','reason':'call_work_prepare'}
    if plan['cursor']>=len(plan['step_ids']):return {**result,'mode':'hold','reason':'work_phases_ended'}
    step=state['work_steps'][plan['step_ids'][plan['cursor']]]
    moving=state['place']!=step['place']
    return {**result,'mode':'action','kind':'moving' if moving else 'work',
        'targets':[step['place'] if moving else step['id']],'destination':step['place'],
        'reason':'execute_work_skill','work':deepcopy(plan),'step':deepcopy(step)}


def prepare(cog):
    return execute('work.prepare',lambda:_prepare(cog),source='life.work')


def _prepare(cog):
    item=(cog.agenda.view() or {}).get('current_item')
    require(enabled(cog) and routine(item),'no current work slot')
    now=cog.clock.now()
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE');state=cog.store.read(db)
        require(not state.get('active') and state['sleep']['status']=='awake' and now<utc(item['end_at']),'work slot unavailable')
        plans=state.setdefault('work_sessions',{})
        ident='workday:'+item['id']
        if ident not in plans:
            plan,steps=plan_for(cog.p.config,state,item,now);plans[ident]=plan
            state.setdefault('work_steps',{}).update({s['id']:s for s in steps})
            state['revision']+=1
            db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
        return {'work':deepcopy(plans[ident]),'steps':[deepcopy(state['work_steps'][key]) for key in plans[ident]['step_ids']],
                'skill':(Path(__file__).parent/'skills/work/SKILL.md').read_text(encoding='utf8')}


def begin(config,state,a,at):
    step=state['work_steps'][a['target']];plan=state['work_sessions'][step['plan_id']]
    require(at<utc(plan['end_at']) and not step.get('ended_at'),'work phase expired')
    require(plan['step_ids'][plan['cursor']]==step['id'] and state['place']==step['place'],'work phase order/place mismatch')
    require(not any(x['id']!=a['id'] and x['target']==a['target'] and x['status'] in {'running','interrupted'} for x in state['activities'].values()),'resume existing work phase')
    a.update(work_mode=plan['mode'],work_task=step['task'],work_title=step['title'],progress=step['progress'],
        duration_seconds=step['seconds'],heartbeat_at=at.isoformat(),work_continues=step['continues'],
        description='左然正在'+step['title'])
    if plan['mode']=='institution':
        visit=state.get('work_visit')
        a['work_arrival']=not visit or visit['place']!=state['place']
        if a['work_arrival']:state['work_visit']={'place':state['place'],'activity_id':a['id'],'started_at':at.isoformat()}


def settle(config,state,a,at,*,recovering=False):
    if not a.get('work_mode') or a['status']!='running':return
    step=state['work_steps'][a['target']];plan=state['work_sessions'][step['plan_id']]
    previous=utc(a['heartbeat_at']);until=min(at,utc(plan['end_at']))
    seconds=max(0,(until-previous).total_seconds())
    if recovering or (at-previous).total_seconds()>90 or state['place']!=a['place']:seconds=0
    a['progress']=min(a['duration_seconds'],a['progress']+seconds);step['progress']=a['progress']
    a.update(heartbeat_at=at.isoformat(),last_progress_at=at.isoformat(),revision=a['revision']+1)
    if step['task']!='break':state['work_continuation']={'task':step['task'],'mode':plan['mode'],'at':at.isoformat()}
    if a['progress']>=a['duration_seconds'] and not step.get('ended_at'):
        step['ended_at']=until.isoformat();plan['cursor']+=1


def heartbeat(cog):
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE');state=cog.store.read(db);a=state['activities'].get(state.get('active'))
        if not a or not a.get('work_mode'):return False
        now=cog.clock.now();settle(cog.p.config,state,a,now)
        a['next_due_at']=(now+timedelta(seconds=cog.p.config['checkpoint_seconds'])).isoformat()
        state.update(revision=state['revision']+1,as_of=now.isoformat())
        db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
        plan=state['work_sessions'][state['work_steps'][a['target']]['plan_id']]
        if a['progress']>=a['duration_seconds'] or now>=utc(plan['end_at']):
            cog.p._commit_locked(db,'work-phase-end:'+a['id'],{'expected_revision':state['revision'],
                'operation':'interrupt','payload':{'activity_id':a['id'],'reason':'本段工作时间结束；不代表事项办结'}},None)
    return True


def departure(state,moving,at):
    visit=state.get('work_visit')
    if visit and visit['place']==state['place'] and moving['target']!=visit['place']:
        moving['work_departure']=state.pop('work_visit')


def event(a,operation):
    if a['work_mode']=='institution':
        return ('work_arrival','左然到达') if operation=='start' and a.get('work_arrival') else None
    if operation in {'start','resume'}:
        prefix='左然继续' if operation=='resume' or a.get('work_continues') else '左然开始'
        if a['work_task']=='break':return 'work_break_start','左然去茶水间接水，稍作休息'
        return 'work_start',prefix+a['work_title']
    if operation in {'interrupt','fail','recover'}:
        if a['work_task']=='break':return 'work_break_end','左然结束了这段休息'
        return 'work_end',('左然结束了这一阶段的' if a['status']=='completed' else '左然暂时放下手中的工作：')+a['work_title']
    return None
