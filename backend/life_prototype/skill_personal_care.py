"""Deterministic personal care steps, settled only by active wall-clock time."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

from application.content_tools import execute
from .clock import utc
from .config import canonical
from .activity_engine import require

ROUTINES = {'wash':'morning_wash','morning_wash':'morning_wash',
            'bedtime_wash':'bedtime_wash','shower':'shower',
            'bedtime_preparation':'bedtime_preparation','await_goodnight':'bedtime_preparation'}
TITLES = {'morning_wash':'晨间洗漱','bedtime_wash':'睡前洗漱',
          'shower':'洗澡及洗后整理','bedtime_preparation':'睡前准备'}
STEPS = {'morning_wash':[('刷牙',120),('洗脸',60),('整理仪容',60)],
         'bedtime_wash':[('刷牙',120),('洗脸',60)],
         'shower':[('洗澡',600),('擦干身体',120),('吹干头发',180)],
         'bedtime_preparation':[('换睡衣',60),('整理床铺',60),('放下手头物品',60)]}


def routine(item):
    if not item or item.get('state_type') in {'commuting','sleeping','eating','working'}: return None
    value=(item.get('constraints') or {}).get('required_routine') or item.get('activity')
    if value in ROUTINES: return ROUTINES[value]
    return {'洗漱':'morning_wash','洗澡':'shower','准备睡觉':'bedtime_preparation'}.get(item.get('intent'))


def enabled(cog):
    return cog.p.config.get('mode')=='local_single_user' and bool(getattr(cog,'resource_root',None))


def identity(item):
    if routine(item)=='bedtime_preparation':
        from .coarse_plan import schedule_day
        return 'care:'+str(schedule_day(utc(item['start_at'])))+':bedtime_preparation'
    return item.get('reference_id') if routine(item)=='shower' and item.get('reference_id') else 'care:'+item['id']


def valid_place(config,item):
    place=item.get('place','')
    name=config['places'].get(place,{}).get('name','')
    return ('bedroom' in place or '卧室' in name) if routine(item)=='bedtime_preparation' else ('bathroom' in place or name in {'卫生间','浴室','洗手间'})


def requirement(cog,state,item,result,at):
    if not valid_place(cog.p.config,item): return {**result,'mode':'blocked','reason':'care_place_mismatch'}
    if routine(item)=='shower':
        prior=[a for a in state['activities'].values() if a['kind']=='showering' and a['target']==identity(item)]
        if any(a['status']=='completed' for a in prior): return {**result,'mode':'hold','reason':'care_completed_wait_awake'}
        if any(not a.get('care_mode') and a['status'] in {'running','interrupted'} for a in prior):
            return {**result,'mode':'action','kind':'showering','targets':[identity(item)],'reason':'finish_existing_shower'}
    plan=state.get('care_plans',{}).get(identity(item))
    if plan and plan.get('completed_at'): return {**result,'mode':'hold','reason':'care_completed_wait_awake'}
    if not plan: return {**result,'mode':'needs_detail','reason':'call_care_prepare'}
    if at>=utc(plan['end_at']): return {**result,'mode':'hold','reason':'care_budget_expired'}
    return {**result,'mode':'action','kind':plan['kind'],'targets':[plan['id']],
            'reason':'execute_care_skill','care':deepcopy(plan)}


def prepare(cog):
    return execute('care.prepare',lambda:_prepare(cog),source='life.care')


def _prepare(cog):
    require(enabled(cog),'care skill disabled')
    item=(cog.agenda.view() or {}).get('current_item')
    name=routine(item)
    require(name and valid_place(cog.p.config,item),'no valid current care slot')
    now=cog.clock.now(); ident=identity(item)
    steps=[{'name':label,'seconds':seconds} for label,seconds in STEPS[name]]
    if name=='shower':
        from .daily_obligations import local_day
        hour=local_day(now).hour
        require(hour>=18 or hour<4,'shower must be in the evening')
        duration=cog.p.config.get('daily_routines',{}).get('shower',{}).get('duration_seconds',900)
        steps[0]['seconds']=max(60,duration-300)
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE');state=cog.store.read(db)
        if name == 'morning_wash':
            from .morning import ready
            require(ready(state, now), 'morning care requires a confirmed wake today')
        plans=state.setdefault('care_plans',{})
        if ident in plans: return {'status':'ready','care':plans[ident]}
        require(state.get('sleep',{}).get('status')=='awake' and not state.get('active'),'pause activity before care planning')
        require(state['place']==item['place'],'arrive at planned care place first')
        duration=sum(s['seconds'] for s in steps)
        require((utc(item['end_at'])-now).total_seconds()>=duration,'insufficient time for care routine')
        plan={'id':ident,'parent_id':item['id'],'routine':name,'title':TITLES[name],
              'kind':'showering' if name=='shower' else 'personal_care','place':item['place'],
              'end_at':item['end_at'],'steps':steps,'duration_seconds':duration,'progress':0,
              'created_at':now.isoformat(),'source':'user_authorized_personal_care_simulation',
              'skill':str(Path(__file__).parent/'skills/personal_care/SKILL.md')}
        plans[ident]=plan;state['revision']+=1
        db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
    return {'status':'ready','care':plan}


def description(activity):
    remaining=activity['progress']
    for step in activity['care_steps']:
        if remaining<step['seconds']: return '左然正在'+step['name']
        remaining-=step['seconds']
    return '左然完成了'+activity['care_title']+('，保持清醒等待晚安' if activity['care_routine']=='bedtime_preparation' else '')


def begin(config,state,activity,at):
    plan=state['care_plans'][activity['target']]
    if plan['routine'] == 'morning_wash':
        from .morning import ready
        require(ready(state, at), 'morning care requires a confirmed wake today')
    require(not plan.get('completed_at') and at<utc(plan['end_at']),'care completed or expired')
    require(state['place']==plan['place'] and activity['kind']==plan['kind'],'care place/kind mismatch')
    require(not any(a['id']!=activity['id'] and a.get('care_mode') and a['target']==activity['target'] and a['status'] in {'running','interrupted'} for a in state['activities'].values()),'resume unfinished care')
    activity.update(care_mode='active_time_simulation',care_routine=plan['routine'],care_title=plan['title'],
                    care_steps=deepcopy(plan['steps']),duration_seconds=plan['duration_seconds'],
                    progress=plan['progress'],heartbeat_at=at.isoformat())
    activity['description']=description(activity)


def settle(config,state,activity,at,*,recovering=False):
    if not activity.get('care_mode') or activity['status']!='running': return
    plan=state['care_plans'][activity['target']]
    previous=utc(activity['heartbeat_at']);until=min(at,utc(plan['end_at']))
    seconds=max(0,(until-previous).total_seconds())
    if recovering or (at-previous).total_seconds()>90 or state['place']!=activity['place']: seconds=0
    activity['progress']=min(activity['duration_seconds'],activity['progress']+seconds)
    activity.update(heartbeat_at=at.isoformat(),last_progress_at=at.isoformat(),revision=activity['revision']+1)
    activity['description']=description(activity);plan['progress']=activity['progress']
    if activity['progress']>=activity['duration_seconds']: plan['completed_at']=at.isoformat()


def heartbeat(cog):
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE');state=cog.store.read(db)
        activity=state['activities'].get(state.get('active'))
        if not activity or not activity.get('care_mode'): return False
        now=cog.clock.now();settle(cog.p.config,state,activity,now)
        activity['next_due_at']=(now+timedelta(seconds=cog.p.config['checkpoint_seconds'])).isoformat()
        state.update(revision=state['revision']+1,as_of=now.isoformat())
        db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
        if activity['progress']>=activity['duration_seconds']:
            cog.p._commit_locked(db,'care-finished:'+activity['id'],{'expected_revision':state['revision'],
                'operation':'interrupt','payload':{'activity_id':activity['id'],'reason':'护理活跃时长已完成'}},None)
    return True
