"""Compatibility projection for retired D2A scores, never a score calculator."""
from copy import deepcopy

RETIRED = {'needs','initial_needs','need_revision','need_source','allowed_dimensions',
           'current_needs','dimensions_status','time_decay','sleep_seconds_per_point',
           'recovery_rate_source','recovery_remainder_seconds','sleepiness_before','sleepiness_after'}


def facts_only(value):
    if isinstance(value,list):return [facts_only(v) for v in value]
    if not isinstance(value,dict):return value
    return {k:facts_only(v) for k,v in value.items() if k not in RETIRED and not
            (k=='dimensions' and isinstance(v,dict) and 'hunger' in v and 'sleepiness' in v)}


def current_state(state):
    result=facts_only(deepcopy(state))
    result['cognition_enabled']=True
    result.pop('test_hunger',None)
    return result
