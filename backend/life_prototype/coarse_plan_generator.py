"""Coarse time/place/intent planning directly against executable skills.

No old state generator, fictional events, needs snapshots or work artifacts.
"""
from datetime import timedelta
from .clock import utc
from .config import digest
from .skill_router import select
from .coarse_plan_schema import site_id


def generate(config,state,now,day_fact,rules,*,version,local,schedule_day,at,route):
    now=utc(now).astimezone(local);day=schedule_day(now);end=at(day+timedelta(days=1),'04:00')
    seed=int(digest([rules.get('seed'),str(day)])[:12],16)
    conflicts=[];items=[];slots=[]
    def reachable(place):
        if place not in config['places']:return False
        try:route(config,state['place'],place);return True
        except ValueError:return False
    def fallback(*places):return next((p for p in places if reachable(p)),state['place'])
    living=fallback('home.f1.living');study=fallback('home.f2.study',living)
    dining=fallback('home.f1.dining',living);bath=fallback('home.f2.bathroom',living)
    bedroom=fallback('home.f2.bedroom',living);office=fallback('firm.office',study)
    def pool(groups,default,offset=0):
        names={n for g in groups for n in rules['locations'].get(g,[])}
        choices=[p for p,v in config['places'].items() if v['name'] in names and reachable(p)]
        return choices[(seed+offset)%len(choices)] if choices else default
    done={a['target'] for a in state.get('activities',{}).values() if a['status']=='completed' and a['kind'] in {'eating','showering'}}
    done.difference_update(ref for ref,p in state.get('meal_plans',{}).items()
                           if p.get('eaten_at') and not p.get('completed_at'))
    done.update(p.get('reference_id') for p in state.get('meal_plans',{}).values() if p.get('completed_at'))
    def slot(start,finish,place,intent,broad='free',activity=None,reference=None):
        if reference and reference in done:return
        slots.append({'start':at(day,start),'finish':at(day,finish),'place':place,'intent':intent,
                      'state_type':broad,'activity':activity or 'free','reference_id':reference})
    def meal(start,finish,place,name):slot(start,finish,place,'用餐','eating',name,f'routine:{day}:{name}')
    workday=day_fact['day_type']=='workday'
    schedule=rules['coarse_day']['windows']['workday' if workday else 'rest_day']
    first_start=at(day,schedule['breakfast'][0])
    from .morning import ready as morning_ready
    morning_awake = morning_ready(state, now)
    if now < first_start:
        slots.append({'start':now,'finish':first_start,
                      'place':state['place'],'intent':'起床及晨间准备' if morning_awake else '夜间休息','state_type':'free',
                      'activity':'home_activity' if morning_awake else 'await_morning','reference_id':None})
    breakfast=pool(['breakfast_shops'],dining) if not workday and seed%3==0 else dining
    meal(*schedule['breakfast'],breakfast,'breakfast')
    if workday:
        morning=office
        if seed%4==1:morning=pool(['courts','procuratorates'],office)
        elif seed%4==2:morning=pool(['work_visits','police'],office)
        slot(*schedule['morning'],morning,'工作','working','working')
        lunch=office if morning==office else pool(['restaurants'],dining,1)
        meal(*schedule['lunch'],lunch,'lunch')
        if seed%3!=0:
            slot(*schedule['rest'],office,'午休','resting','resting')
        slot(*schedule['afternoon'],office,'工作','working','working')
    else:
        balcony=fallback('home.f1.balcony',living)
        slot(*schedule['morning'],study,'家中活动',activity='home_activity')
        meal(*schedule['lunch'],dining,'lunch')
        if seed%2==0:
            slot(*schedule['rest'],living,'午休','resting','resting')
        outing=pool(['bookstores','walks','shopping','markets','groceries'],study,2)
        slot(*schedule['afternoon'],outing,'家中活动' if outing==study else '外出活动',activity='home_activity' if outing==study else 'outing')
        sport=pool(['gym','swimming','shooting'],living,3) if seed%2 else living
        slot(*schedule['exercise'],sport,'运动','exercising','exercising')
    evening=rules['coarse_day']['windows']['evening']
    supper=pool(['restaurants'],dining,4) if seed%4==0 else dining
    meal(*evening['dinner'],supper,'dinner')
    # Reserve daily chores independently of optional leisure choices.
    slot(*evening['housework'],living,'家务',activity='housework')
    # The coarse plan chooses the site.  A skill later chooses the activity
    # within that site and any room inside home or the firm.
    evening_roll=seed%4
    if workday and evening_roll==1:
        evening_place,evening_state,evening_activity=office,'working','working'
    elif evening_roll==0:
        evening_place=pool(['cinemas','theatre','walks'],living,5)
        evening_state,evening_activity='free','outing' if evening_place!=living else 'free'
    else:
        evening_place,evening_state,evening_activity=living,'free','home_activity'
    shower_start,shower_end=evening['shower']
    if evening_activity=='home_activity':
        # Pick once per day, independently of the bedtime wash. Leave room
        # for ordinary home activities after an earlier shower.
        candidates=[value for value in ('20:00','20:40','21:20',shower_start)
                    if at(day,evening['housework'][1])<=at(day,value)<=at(day,shower_start)]
        shower_start=candidates[(seed//4)%len(candidates)] if candidates else shower_start
        duration=at(day,evening['shower'][1])-at(day,evening['shower'][0])
        shower_end=(at(day,shower_start)+duration).strftime('%H:%M')
        slot(evening['housework'][1],shower_start,evening_place,'晚间活动',evening_state,evening_activity)
        if at(day,shower_end)<at(day,evening['leisure'][1]):
            slot(shower_end,evening['leisure'][1],evening_place,'晚间活动',evening_state,evening_activity)
    else:
        slot(evening['housework'][1],evening['leisure'][1],evening_place,
             '工作' if evening_state=='working' else '晚间活动',evening_state,evening_activity)
    slot(shower_start,shower_end,bath,'洗澡',activity='shower',reference=f'routine:{day}:shower')
    slot(*evening['wash'],bath,'洗漱',activity='bedtime_wash')
    # A late activation still leaves an evening shower opportunity, never a
    # claim that a missed shower was performed while the service was offline.
    for s in slots:
        if s['activity']=='shower':
            s['start']=max(s['start'],at(day,'18:00'))
            if s['finish']<=now:
                s['start']=now;s['finish']=now+timedelta(minutes=20)
    # Sleep preparation follows actual late shower opportunity as well.
    shower=next((s for s in slots if s['activity']=='shower'),None)
    wash=next((s for s in slots if s['activity']=='bedtime_wash'),None)
    if wash and shower and wash['start']<shower['finish']:
        wash['start']=shower['finish'];wash['finish']=wash['start']+timedelta(minutes=5)
    slots.sort(key=lambda s:s['start'])
    cursor=now;location=state['place']
    def append(finish,place,broad,intent,activity,**extra):
        nonlocal cursor
        finish=min(finish,end)
        if finish<=cursor:return
        item={'id':f'agenda:{day}:{len(items)}','start_at':cursor.isoformat(),'end_at':finish.isoformat(),
            'place':place,'place_name':config['places'][place]['name'],'state_type':broad,
            'intent':intent,'activity':activity,'kind':{'commuting':'commute','working':'work','eating':'meal','resting':'rest'}.get(broad,broad),
            'semantics':'planned_not_observed',**extra}
        if broad!='commuting' and select(item) is None:raise ValueError('coarse intention has no skill')
        items.append(item);cursor=finish
    def move(destination):
        nonlocal location
        path,seconds=route(config,location,destination)
        # Moving between rooms is fine-plan detail, not commuting.
        if site_id(location)==site_id(destination):
            location=destination
            return True
        if seconds:
            if cursor+timedelta(seconds=seconds)>=end:return False
            append(cursor+timedelta(seconds=seconds),location,'commuting',None,'moving',
                   destination=destination,destination_name=config['places'][destination]['name'],route=path)
        location=destination;return True
    for s in slots:
        if s['finish']<=cursor:continue
        _,seconds=route(config,location,s['place'])
        if site_id(location)==site_id(s['place']): seconds=0
        if cursor+timedelta(seconds=seconds)>=s['finish'] and s['activity'] not in {'shower','bedtime_wash'} and s['state_type']!='eating':
            conflicts.append({'reason':'insufficient_time_after_travel','intent':s['intent'],'place':s['place']});continue
        if s['start']>cursor+timedelta(seconds=seconds):
            next_start=s['start']-timedelta(seconds=seconds)
            # Coarse windows are continuous broad periods.  Small preparation
            # and buffer gaps belong to the preceding broad activity; skills
            # may finish their concrete action earlier and simply hold.
            if items and items[-1]['state_type']!='commuting' and site_id(items[-1]['place'])==site_id(location):
                items[-1]['end_at']=next_start.isoformat()
            cursor=next_start
        if not move(s['place']):break
        finish=s['finish']
        if s['activity']=='shower':finish=max(finish,cursor+timedelta(minutes=20))
        if s['activity']=='bedtime_wash':finish=max(finish,cursor+timedelta(minutes=5))
        if s['state_type']=='eating':finish=max(finish,cursor+timedelta(minutes=30))
        append(finish,location,s['state_type'],s['intent'],s['activity'],reference_id=s['reference_id'])
    if cursor<end and move(bedroom):
        append(end,bedroom,'free','准备睡觉','bedtime_preparation')
    return {'version':version,'date':str(day),'day_start_hour':4,'source':'skill_coarse_planner',
        'rules_hash':digest(rules),'world_hash':digest(config),'calendar':day_fact,'generated_at':now.isoformat(),
        'template':'workday' if workday else 'rest_day','items':items,'conflicts':conflicts,
        'omitted_branches':[],'place_adaptations':[],
        'commitments':[c for c in state.get('commitments',[]) if c['status']=='confirmed'],
        'semantics':'site-level coarse intentions only; room movement and activity choices are fine detail; actual execution produces events'}
