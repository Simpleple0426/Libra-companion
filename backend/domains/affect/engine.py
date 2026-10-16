"""Pure OCC-style elicitation and deterministic, read-only time projection."""
import copy
import math
from datetime import timedelta
from .contracts import SETTINGS, iso, timestamp, model_output

AXES=('pleasure','arousal','dominance')


def initial(now=None):
    return {'schema_version':1,'updated_at':iso(now),'last_effective_interaction_at':None,
            'mood':dict(SETTINGS['default_mood']), 'needs':{k:{'value':v[0],'baseline':v[0],'recovery_time_min':v[1]} for k,v in SETTINGS['needs'].items()},
            'instances':[]}


def aggregate(instances,now):
    totals={}
    for item in instances:
        cfg=SETTINGS['emotions'][item['type']]
        age=(timestamp(now)-timestamp(item['activated_at'])).total_seconds()/60
        decay=max(0,age-cfg['hold_time_min'])
        if item.get('status','active')!='active' or age<0 or decay>=5*cfg['half_life_min']:continue
        intensity=item['initial_intensity']*2**(-decay/cfg['half_life_min'])
        totals[item['type']]=1-(1-totals.get(item['type'],0))*(1-intensity)
    return totals


def project(state,now=None):
    state=copy.deepcopy(state);now=timestamp(now);cursor=timestamp(state['updated_at'])
    if now<cursor:now=cursor
    # Global minute integration boundaries keep GET frequency out of the result.
    # Event commits are the only new integration anchors.
    while cursor<now:
        boundary=cursor.replace(second=0,microsecond=0)+timedelta(minutes=1)
        end=min(now,boundary)
        bucket=cursor.replace(second=0,microsecond=0)
        sample_at=max([bucket]+[timestamp(i['activated_at']) for i in state['instances'] if bucket<timestamp(i['activated_at'])<=cursor])
        emotions=aggregate(state['instances'],sample_at)
        if not emotions:
            # No active sources can reappear without another committed event.
            future=[timestamp(i['activated_at']) for i in state['instances'] if timestamp(i['activated_at'])>cursor]
            if not future:end=now
        dt=(end-cursor).total_seconds()/60
        if emotions:
            total=sum(emotions.values());strength=1-math.prod(1-v for v in emotions.values())
            target={axis:sum(SETTINGS['emotions'][kind]['pad'][j]*value for kind,value in emotions.items())/total for j,axis in enumerate(AXES)}
            step=1-math.exp(-dt*strength/SETTINGS['mood_change_time_min'])
        else:
            target=SETTINGS['default_mood'];step=1-math.exp(-dt/SETTINGS['mood_recovery_time_min'])
        for axis in AXES:state['mood'][axis]+=step*(target[axis]-state['mood'][axis])
        for key,need in state['needs'].items():
            target=need['baseline']
            need['value']+=(max(0,min(1,target))-need['value'])*(1-math.exp(-dt/need['recovery_time_min']))
        cursor=end
    state['updated_at']=iso(now)
    for item in state['instances']:
        cfg=SETTINGS['emotions'][item['type']]
        if (now-timestamp(item['activated_at'])).total_seconds()/60>=cfg['hold_time_min']+5*cfg['half_life_min']:item['status']='inactive'
    state['instances']=[i for i in state['instances'] if i.get('status','active')=='active']
    state['aggregated_emotions']=aggregate(state['instances'],now)
    return state


def appraise(payload,raw):
    value=model_output('appraisal',raw)
    if value['event_id']!=payload['event']['event_id']:raise ValueError('event_id_mismatch')
    goals={g['goal_id']:g for g in SETTINGS['core_goals']};standards={s['standard_id']:s for s in SETTINGS['standards']}
    seen=set()
    for goal in value['goal_appraisals']:
        parent=goals.get(goal['parent_core_goal_id'])
        if not parent or goal['target']!=parent['target']:raise ValueError('invalid_goal_reference')
        key=(goal['parent_core_goal_id'],goal['prospect_status'])
        if key in seen:raise ValueError('duplicate_goal_appraisal')
        seen.add(key);status=goal['prospect_status']
        if status=='anticipated':
            if goal['impact']=='neutral' or goal['prospect'] is None or timestamp(goal['prospect']['valid_until'])<=timestamp(payload['current_context']['current_time']):raise ValueError('invalid_future_prospect')
        elif goal['prospect'] is not None:raise ValueError('unexpected_prospect')
        goal['desire_force']=max(0,min(1,parent['base_desire_force']+goal.pop('context_adjustment')))
    seen=set()
    for standard in value['standard_appraisals']:
        sid=standard['standard_id'];key=(sid,standard['actor'])
        if sid not in standards or key in seen:raise ValueError('invalid_standard_reference')
        seen.add(key);standard['importance']=standards[sid]['importance']
    return value


def elicit(appraisal,now):
    potentials={}
    def candidate(kind,potential):potentials[kind]=max(potentials.get(kind,0),potential)
    for goal in appraisal['goal_appraisals']:
        if goal['impact']=='neutral':continue
        positive=goal['impact']=='promote';status=goal['prospect_status'];potential=goal['impact_strength']*goal['desire_force']
        if status=='anticipated':
            kind='hope' if positive else 'fear'
            candidate(kind,potential)
        else:
            kind=('happy_for' if positive else 'sorry_for') if goal['target'] in {'user','other'} else ('joy' if positive else 'distress')
            candidate(kind,potential)
    for standard in appraisal['standard_appraisals']:
        if standard['evaluation']=='neutral':continue
        positive=standard['evaluation']=='praiseworthy'
        kind=('pride' if positive else 'shame') if standard['actor']=='libra' else ('admiration' if positive else 'reproach')
        candidate(kind,standard['evaluation_strength']*standard['importance'])
    for a,b,compound in [('pride','joy','gratification'),('admiration','joy','gratitude'),('shame','distress','remorse'),('reproach','distress','anger')]:
        if potentials.get(a,0)>SETTINGS['emotions'][a]['threshold'] and potentials.get(b,0)>SETTINGS['emotions'][b]['threshold']:candidate(compound,min(potentials[a],potentials[b]))
    instances=[]
    for kind,potential in potentials.items():
        threshold=SETTINGS['emotions'][kind]['threshold']
        if potential>threshold:instances.append({'emotion_instance_id':appraisal['event_id']+':'+kind,'source_event_id':appraisal['event_id'],'type':kind,'initial_intensity':(potential-threshold)/(1-threshold),'activated_at':iso(now),'status':'active'})
    return instances


def update_needs(state,raw):
    value=model_output('need_update',raw);seen=set()
    for change in value['need_updates']:
        key=change['need']
        if key in seen:raise ValueError('duplicate_need')
        seen.add(key);delta=SETTINGS['strength'][change['strength']]*{'increase':1,'decrease':-1,'neutral':0}[change['direction']]
        need=state['needs'][key];need['value']=max(0,min(1,need['value']+delta))
    return value
