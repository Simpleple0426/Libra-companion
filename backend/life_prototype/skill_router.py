"""One routing policy for coarse intentions and the ten life skills."""
from importlib import import_module

MODULES={'home_activity':'skill_home_activity','work':'skill_work','dining':'skill_dining','housework':'skill_housework',
    'personal_care':'skill_personal_care','exercise':'skill_exercise','television':'skill_television',
    'rest':'skill_rest','outing':'skill_outing'}


def select(item):
    if not item or item.get('state_type') in {'commuting','sleeping'}:return None
    if item.get('activity') == 'await_morning': return 'morning_wait'
    if item.get('state_type')=='eating':return 'dining'
    module=import_module('.'+MODULES['home_activity'],__package__)
    if module.routine(item):return 'home_activity'
    for name in ('work','housework','personal_care','exercise','television','outing','rest'):
        module=import_module('.'+MODULES[name],__package__)
        if module.routine(item):return name
    if item.get('state_type')=='free' and item.get('intent')=='晚间活动':return 'evening'
    if item.get('intent')=='阅读' or item.get('activity')=='reading':return 'reading'
    if item.get('intent')=='看电影' or item.get('activity') in {'watch_movie','watch_show'}:return 'movie'
    return None


def executor(cog,item):
    name=select(item)
    if name not in MODULES:return None
    module=import_module('.'+MODULES[name],__package__)
    return module if module.enabled(cog) else None
