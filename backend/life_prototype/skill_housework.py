"""Catalog-backed chores with active human phases and independent machine timers."""
from copy import deepcopy
from datetime import timedelta
from application.content_tools import execute
from .clock import utc
from .config import canonical
from .activity_engine import require
from .skill_dining import travel

ROUTINES={'clean_dishes','tidy','housework','household_tidy','laundry','dry_laundry','fold_laundry'}
WASH_SECONDS=1800
AIR_SECONDS=14400


def routine(item):
    if not item or item.get('state_type') in {'commuting','working','eating','sleeping'}: return None
    value=(item.get('constraints') or {}).get('housework_routine') or item.get('activity')
    if value in ROUTINES: return value
    legacy=item.get('source_window') or []
    if item.get('intent')=='家务' and legacy and legacy[0] in ROUTINES: return legacy[0]
    return 'housework' if item.get('intent')=='家务' else None


def enabled(cog):
    return cog.p.config.get('mode')=='local_single_user' and bool(getattr(cog,'resource_root',None))


def object_named(config,name,place=None):
    return next((key for key,obj in config['objects'].items() if obj.get('name')==name
                 and obj.get('status')=='confirmed' and obj.get('available',True)
                 and obj.get('location_status') is None and (place is None or obj['parent']==place)),None)


def steps_for(config,state,item):
    """Choose from actual catalog identities. No invented inventory/dirty counts."""
    name=routine(item);place=item['place'];objects=config['objects']
    steps=[]
    def add(title,seconds,room,resources,effect=None):
        if not all(resources): return False
        steps.append({'title':title,'seconds':seconds,'place':room,'resources':resources,
                      'effect':effect or {},'progress':0})
        return True
    washer=object_named(config,'洗衣机');rail=object_named(config,'晾衣杆');wardrobe=object_named(config,'衣柜')
    batches=state.get('laundry_batches',{})
    batch_id=item.get('constraints',{}).get('laundry_batch_id')
    batch=batches.get(batch_id) if batch_id else next((b for b in batches.values() if b['status'] in {'washed','carrying_wet','dry','carrying_dry'}),None)
    if batch_id and (not batch or batch['status'] not in {'washed','carrying_wet','dry','carrying_dry'}): return [],'laundry_dependency_not_ready'
    if name in {'dry_laundry','fold_laundry'} or (name in {'housework','household_tidy'} and batch):
        if not batch: return [],'no_washed_or_dry_laundry'
        if batch['status'] in {'washed','carrying_wet'}:
            if not washer or not rail: return [],'laundry_equipment_missing'
            if batch['status']=='washed': add('取出洗好的衣物',60,objects[washer]['parent'],[washer],{'batch':batch['id'],'status':'carrying_wet'})
            add('晾晒洗好的衣物',120,objects[rail]['parent'],[rail],{'batch':batch['id'],'status':'airing'})
        else:
            if not rail or not wardrobe: return [],'laundry_equipment_missing'
            if batch['status']=='dry': add('收下晾干的衣物',60,objects[rail]['parent'],[rail],{'batch':batch['id'],'status':'carrying_dry'})
            add('叠好衣物并放回衣柜',180,objects[wardrobe]['parent'],[wardrobe],{'batch':batch['id'],'status':'stored'})
    elif name=='laundry':
        if not washer: return [],'washing_machine_missing'
        if any(b['status']!='stored' for b in batches.values()): return [],'finish_existing_laundry_first'
        add('放入自用衣物并启动洗衣机',180,objects[washer]['parent'],[washer],{'start_machine':washer,'type':'wash','seconds':WASH_SECONDS})
    elif name=='clean_dishes':
        sink=object_named(config,'水槽');plates=object_named(config,'碗盘');cloth=object_named(config,'抹布');table=object_named(config,'餐桌')
        sponge=object_named(config,'海绵');soap=object_named(config,'洗洁精')
        if not all([sink,plates,cloth,table,sponge,soap]): return [],'dishwashing_resources_missing'
        add('收拾餐桌上的餐具',60,objects[table]['parent'],[table,plates])
        add('清洗餐具并取用抹布',120,objects[sink]['parent'],[sink,plates,sponge,soap,cloth])
        add('擦拭餐桌',60,objects[table]['parent'],[table,cloth])
        add('放回抹布',30,objects[cloth]['parent'],[cloth])
    else:
        table=object_named(config,'茶几',place) or object_named(config,'餐桌',place)
        sofa=object_named(config,'沙发',place);robot=object_named(config,'扫地机器人',place)
        cloth=object_named(config,'抹布')
        # Prefer a different local task after a completed one, without assuming dirt.
        previous=[p for p in state.get('housework_plans',{}).values() if p.get('completed_at') and p['coarse_place']==place]
        turn=len(previous)%3
        if robot and turn==2 and not any(m['object']==robot and m['status']=='running' for m in state.get('household_machines',{}).values()):
            add('启动扫地机器人清扫客厅',60,place,[robot],{'start_machine':robot,'type':'vacuum','seconds':600})
        elif table and cloth and turn==1:
            add('取用抹布',30,objects[cloth]['parent'],[cloth])
            add('擦拭'+objects[table]['name'],120,place,[table,cloth])
            add('放回抹布',30,objects[cloth]['parent'],[cloth])
        elif sofa or table:
            add('整理'+('沙发和茶几' if sofa and table else objects[sofa or table]['name']),120,place,[x for x in [sofa,table] if x])
        elif wardrobe and objects[wardrobe]['parent']==place:
            add('整理衣柜中的自用衣物',180,place,[wardrobe])
    return steps,None if steps else 'no_catalogued_housework_here'


def current_plan(state,item):
    return next((p for p in state.get('housework_plans',{}).values() if p['parent_id']==item['id']),None)


def pending_plan(state,item):
    name=routine(item)
    batch_id=item.get('constraints',{}).get('laundry_batch_id')
    return next((p for p in state.get('housework_plans',{}).values() if not p.get('completed_at')
                 and (p['routine']!='clean_dishes' or name=='clean_dishes')
                 and (not item.get('constraints',{}).get('meal_cleanup_ref') or
                      p.get('meal_cleanup_ref')==item['constraints']['meal_cleanup_ref'])
                 and (not batch_id or any(state['housework_steps'][key]['effect'].get('batch')==batch_id for key in p['step_ids']))
                 and (name in {'housework','household_tidy'} or
                      (p['routine']==name and (p['coarse_place']==item['place'] or name in {'laundry','dry_laundry','fold_laundry'})))),None)


def requirement(cog,state,item,result,at):
    if not str(item.get('place','')).startswith('home'): return {**result,'mode':'blocked','reason':'housework_requires_home'}
    plan=current_plan(state,item)
    if not plan:
        steps,reason=steps_for(cog.p.config,state,item)
        pending=pending_plan(state,item)
        return {**result,'mode':'needs_detail' if steps or pending else 'hold',
                'reason':'call_housework_prepare' if steps or pending else reason}
    if plan.get('completed_at'): return {**result,'mode':'hold','reason':'housework_completed'}
    step=state['housework_steps'][plan['step_ids'][plan['cursor']]]
    if utc(at)>=utc(plan['end_at']): return {**result,'mode':'hold','reason':'housework_budget_expired'}
    try: seconds=travel(cog.p.config,state['place'],step['place'])
    except (ValueError,KeyError): return {**result,'mode':'blocked','reason':'housework_place_unreachable'}
    active=state['activities'].get(state.get('active'),{})
    if not (active.get('kind')=='housework' and active.get('target')==step['id']):
        if seconds+step['seconds']-step['progress']>(utc(plan['end_at'])-utc(at)).total_seconds():
            return {**result,'mode':'hold','reason':'housework_wait_next_slot'}
    moving=state['place']!=step['place']
    return {**result,'mode':'action','kind':'moving' if moving else 'housework',
            'targets':[step['place'] if moving else step['id']],'destination':step['place'],
            'reason':'execute_housework_skill','housework':deepcopy(plan),'step':deepcopy(step)}


def prepare(cog):
    return execute('housework.prepare',lambda:_prepare(cog),source='life.housework')


def _prepare(cog):
    require(enabled(cog),'housework skill disabled')
    item=(cog.agenda.view() or {}).get('current_item')
    from .skill_dining import cleanup_item
    item=cleanup_item(cog.p.config,cog.p.snapshot(),item) or item
    require(routine(item),'no current housework slot')
    require(item['place'].startswith('home'),'housework requires home')
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE');state=cog.store.read(db)
        old=current_plan(state,item)
        if old: return {'status':'ready','housework':old}
        require(not state.get('active') and state['sleep']['status']=='awake','pause current activity first')
        plans=state.setdefault('housework_plans',{})
        pending=pending_plan(state,item)
        if pending:
            pending.update(parent_id=item['id'],end_at=item['end_at']);plan=pending
        else:
            steps,reason=steps_for(cog.p.config,state,item);require(steps,reason or 'no housework available')
            ident='housework:'+item['id'];ids=[]
            for i,step in enumerate(steps):
                key=ident+':'+str(i);ids.append(key)
                state.setdefault('housework_steps',{})[key]={**step,'id':key,'plan_id':ident}
            plan={'id':ident,'parent_id':item['id'],'routine':routine(item),'coarse_place':item['place'],
                  'end_at':item['end_at'],'step_ids':ids,'cursor':0,'created_at':cog.clock.now().isoformat(),
                  'source':'user_authorized_catalog_housework_simulation'}
            plans[ident]=plan
        if item.get('constraints',{}).get('meal_cleanup_ref'):
            plan['meal_cleanup_ref']=item['constraints']['meal_cleanup_ref']
        state['revision']+=1
        db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
    return {'status':'ready','housework':plan}


def begin(config,state,activity,at):
    step=state['housework_steps'][activity['target']];plan=state['housework_plans'][step['plan_id']]
    require(not step.get('completed_at') and at<utc(plan['end_at']),'housework completed or expired')
    require(plan['step_ids'][plan['cursor']]==step['id'],'housework phases must execute in order')
    require(state['place']==step['place'],'housework step place mismatch')
    require(all(key in config['objects'] and config['objects'][key].get('available',True) for key in step['resources']),'housework resource unavailable')
    require(not any(a['id']!=activity['id'] and a.get('housework_mode') and a['target']==activity['target'] and a['status'] in {'running','interrupted'} for a in state['activities'].values()),'resume unfinished housework')
    activity.update(housework_mode='active_time_simulation',housework_title=step['title'],
                    duration_seconds=step['seconds'],progress=step['progress'],heartbeat_at=at.isoformat(),
                    description='左然正在'+step['title'])


def apply_effect(state,step,at):
    effect=step['effect']
    if effect.get('start_machine'):
        ident='machine:'+step['id'];obj=effect['start_machine']
        require(not any(m['object']==obj and m['status']=='running' for m in state.get('household_machines',{}).values()),'machine already running')
        state.setdefault('household_machines',{})[ident]={'id':ident,'object':obj,'type':effect['type'],
            'status':'running','started_at':at.isoformat(),'finishes_at':(at+timedelta(seconds=effect['seconds'])).isoformat(),
            'source':'autonomous_simulation_timer','step_id':step['id'],'place':step['place']}
        if effect['type']=='wash':
            state.setdefault('laundry_batches',{})[ident]={'id':ident,'machine_id':ident,'status':'washing',
                'owner':'left_personal_clothes','place':step['place'],'source':'user_authorized_abstract_laundry_batch'}
            followup='laundry-followup:'+ident+':hang'
            state.setdefault('household_followups',{})[followup]={'id':followup,'batch_id':ident,'phase':'hang',
                'title':'晾晒洗好的衣物','status':'waiting','created_at':at.isoformat(),
                'dependency':'washing_completed','expected_ready_at':state['household_machines'][ident]['finishes_at'],
                'source':'committed_laundry_dependency'}
    elif effect.get('batch'):
        batch=state['laundry_batches'][effect['batch']]
        expected={'carrying_wet':'washed','airing':'carrying_wet','carrying_dry':'dry','stored':'carrying_dry'}
        require(batch['status']==expected[effect['status']],'laundry phase mismatch')
        batch.update(status=effect['status'],place=step['place'])
        if batch['status']=='airing': batch['dry_at']=(at+timedelta(seconds=AIR_SECONDS)).isoformat()
        if batch['status']=='stored': batch['stored_at']=at.isoformat()


def settle(config,state,activity,at,*,recovering=False):
    if not activity.get('housework_mode') or activity['status']!='running': return
    step=state['housework_steps'][activity['target']];plan=state['housework_plans'][step['plan_id']]
    previous=utc(activity['heartbeat_at']);until=min(at,utc(plan['end_at']))
    seconds=max(0,(until-previous).total_seconds())
    if recovering or (at-previous).total_seconds()>90 or state['place']!=activity['place']: seconds=0
    activity['progress']=min(activity['duration_seconds'],activity['progress']+seconds)
    activity.update(heartbeat_at=at.isoformat(),last_progress_at=at.isoformat(),revision=activity['revision']+1)
    step['progress']=activity['progress']
    if activity['progress']>=activity['duration_seconds'] and not step.get('completed_at'):
        apply_effect(state,step,until)
        step['completed_at']=until.isoformat();plan['cursor']+=1
        if plan['cursor']==len(plan['step_ids']):
            plan['completed_at']=until.isoformat()
            if plan.get('meal_cleanup_ref'):
                meal=state['meal_plans'][plan['meal_cleanup_ref']]
                meal['cleanup_completed_at']=until.isoformat()
                meal['completed_at']=until.isoformat()
        activity['description']='左然已完成：'+step['title']


def heartbeat(cog):
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE');state=cog.store.read(db)
        activity=state['activities'].get(state.get('active'))
        if not activity or not activity.get('housework_mode'): return False
        now=cog.clock.now();settle(cog.p.config,state,activity,now)
        activity['next_due_at']=(now+timedelta(seconds=cog.p.config['checkpoint_seconds'])).isoformat()
        state.update(revision=state['revision']+1,as_of=now.isoformat())
        db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
        if activity['progress']>=activity['duration_seconds']:
            cog.p._commit_locked(db,'housework-finished:'+activity['id'],{'expected_revision':state['revision'],
                'operation':'interrupt','payload':{'activity_id':activity['id'],'reason':'家务步骤活跃时长已完成'}},None)
    return True


def tick_machines(cog):
    """Autonomous timers advance while away/asleep/offline; no human work inferred."""
    from .event_store import append
    now=cog.clock.now();changed=False
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE');state=cog.store.read(db)
        events=[]
        for machine in state.get('household_machines',{}).values():
            if machine['status']!='running' or now<utc(machine['finishes_at']): continue
            machine.update(status='completed',completed_at=machine['finishes_at'])
            if machine['type']=='wash':
                state['laundry_batches'][machine['id']]['status']='washed'
                text='洗衣机已洗完，衣物等待左然取出晾晒'
            else: text='扫地机器人已完成本次清扫'
            events.append((machine['id'],machine['finishes_at'],text,'household_machine_completed'))
        for batch in state.get('laundry_batches',{}).values():
            if batch['status']!='airing' or now<utc(batch['dry_at']): continue
            batch['status']='dry'
            events.append(('dry:'+batch['id'],batch['dry_at'],'衣物按模拟晾晒时间已晾干，等待左然收衣','laundry_dry'))
        for ident,at,text,kind in events:
            state['revision']+=1
            append(db,'household-timer:'+ident,{'operation':'household_timer','description':text,'kind':kind},
                {'event_id':'household-timer:'+ident,'revision':state['revision'],'occurred_at':at,
                 'recorded_at':now.isoformat(),'source':'autonomous_household_simulation_timer'},state,cog.p.config)
            changed=True
        if changed: db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(state),))
    return changed
