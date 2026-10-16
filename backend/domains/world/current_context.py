"""Observed, expiring current context; separate consumer projections."""
import json
import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo
from domains.affect.contracts import iso, timestamp, CONFIG

POLICY=json.loads((CONFIG/'current_context_v1.json').read_text(encoding='utf-8'))
TTL=POLICY['ttl_minutes']

ACTIVITIES={'working','commuting','exercising','eating','leisure','resting','sleeping','studying','socializing','household','personal_care','traveling','unavailable','other','unknown'}


def observed(value,at,ref,kind='authoritative_state',confidence=1,ttl=None):
    return {'value':value,'observed_at':iso(at) if at else None,'source_type':kind,'source_ref':ref,
            'confidence':confidence if at else 0,'valid_until':iso(timestamp(at)+timedelta(minutes=ttl)) if at and ttl else None}


def build(now=None,*,attributes=None,life=None,user_status=None,status_at=None,last_interaction=None,
          messages=(),message_counts=None,trigger_event_id=None,is_workday=None):
    now=timestamp(now);attributes=attributes or {};life=life or {}
    def use(obs,path):
        if obs['valid_until'] and timestamp(obs['valid_until'])<=now:
            return {**obs,'value':'unknown','confidence':0}
        return obs
    at=attributes.get('snapshot_at');activity=life.get('state_type') or life.get('state') or attributes.get('current_state','unknown')
    if activity=='free':activity='leisure'
    if activity not in ACTIVITIES:activity='unknown'
    life_at=life.get('start_time') or at
    rawfatigue=attributes.get('fatigue')
    fatigue=observed(max(0,min(1,float(rawfatigue)/100)) if rawfatigue is not None else None,at,'libra_attribute_snapshot:'+str(attributes.get('id','')),ttl=TTL['libra.fatigue'])
    fatigue=use(fatigue,'libra.fatigue')
    if fatigue['value']=='unknown':fatigue['value']=None
    user={'status':use(observed(user_status if status_at and user_status else 'unknown',
        status_at, 'user_home_status', 'explicit_user_statement', ttl=TTL['user.status']), 'user.status')}
    activity_obs=observed(activity,life_at,'libra_state_event:'+str(life.get('id','')))
    if life.get('end_time'):activity_obs['valid_until']=iso(life['end_time'])
    activity_obs=use(activity_obs,'libra.activity')
    minutes=max(0,int((now-timestamp(last_interaction)).total_seconds()/60)) if last_interaction else None
    local=now.astimezone(ZoneInfo('Asia/Shanghai'))
    location_name=life.get('location') or life.get('end_location') or life.get('from_location') or 'unknown'
    location_kind=POLICY['location_aliases'].get(location_name,'other' if location_name!='unknown' else 'unknown')
    if location_name == '餐厅':
        location_name = '家里的餐厅'
    if activity=='commuting' and life.get('from_location') and life.get('end_location'):
        location_name=life['from_location']+' → '+life['end_location']
        location_kind='transit'
    location=observed(location_name,life_at,'libra_state_event:'+str(life.get('id','')))
    location['valid_until']=activity_obs['valid_until']
    location=use(location,'libra.location_name')
    if location['value']=='unknown':location_kind='unknown'
    last_user=max((iso(m['created_at']) for m in messages if m.get('role')=='user'),default=None)
    last_libra=max((iso(m['created_at']) for m in messages if m.get('role')=='assistant'),default=None)
    return {'schema_version':'1.0','context_id':'ctx_'+uuid.uuid4().hex,'trigger_event_id':trigger_event_id,
        'generated_at':iso(now),'timezone':'Asia/Shanghai','temporal':{'local_time':local.isoformat(),
            'day_phase':'night' if local.hour<6 or local.hour>=23 else 'morning' if local.hour<12 else 'afternoon' if local.hour<18 else 'evening',
            'is_workday':is_workday},
        'libra':{'activity':activity_obs,'fatigue':fatigue,
                 'location_name':location,
                 'location_type':{**location,'value':location_kind,'source_type':'derived_rule'},
                 'availability':observed('asleep' if activity_obs['value']=='sleeping' else 'working' if activity_obs['value']=='working' else 'free',now,'availability_rule_v1','derived_rule',.8)},
        'user':user,'interaction':{'last_effective_interaction_at':iso(last_interaction) if last_interaction else None,
            'minutes_since_last_interaction':minutes,'conversation_status':'active' if minutes is not None and minutes<5 else 'paused' if minutes is not None else 'unknown',
            'last_user_message_at':last_user,'last_libra_message_at':last_libra,
            'messages_last_60m':message_counts['messages_last_60m'] if message_counts is not None else sum(0<=(now-timestamp(m['created_at'])).total_seconds()<=3600 for m in messages),
            'messages_today':message_counts['messages_today'] if message_counts is not None else sum(timestamp(m['created_at']).astimezone(ZoneInfo('Asia/Shanghai')).date()==local.date() for m in messages)},
        # Fixed married identity; the stage key also serves corpus retrieval.
        'relationship':{
            'relationship_stage':'established_partner',
            'relationship_roles':['lover','spouse'],
            'identity_status':'stable',
            'relationship_description':'婚后热恋',
        }}


def project(snapshot,consumer):
    if consumer == 'response':
        return {**({'local_life': snapshot['local_life']} if 'local_life' in snapshot else {}),
                'current_time': (snapshot.get('temporal') or {}).get('local_time', snapshot.get('generated_at')),
                'libra': {key: snapshot.get('libra', {}).get(key, {}).get('value', 'unknown')
                          for key in ('activity', 'location_name')},
                'user': {'status': snapshot.get('user', {}).get('status', {}).get('value', 'unknown')}}
    if consumer not in {'appraisal','need','initiative','expression'}:raise ValueError('unknown_context_consumer')
    out={'current_time':snapshot['generated_at'],'libra':{'activity':snapshot['libra']['activity']['value'],'fatigue':snapshot['libra']['fatigue']['value']},
         'user':{'status':snapshot['user']['status']['value']},
         'interaction':dict(snapshot['interaction']),'relationship':dict(snapshot['relationship'])}
    if consumer=='appraisal':
        out['timezone']=snapshot.get('timezone', 'Asia/Shanghai')
        out['temporal']=dict(snapshot.get('temporal') or {})
        for field in ('location_name', 'location_type'):
            out['libra'][field]=(snapshot['libra'].get(field) or {}).get('value', 'unknown')
        out['interaction']={key:snapshot['interaction'].get(key) for key in (
            'last_effective_interaction_at', 'minutes_since_last_interaction')}
    if consumer=='need':
        out['interaction'].pop('minutes_since_last_interaction',None)
        out['interaction'].pop('last_effective_interaction_at',None)
    return out

