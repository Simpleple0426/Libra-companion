"""Television on/off lifecycle only; no programme selection or viewing progress."""
from datetime import timedelta
from application.content_tools import execute
from .skill_personal_care import enabled
from .clock import utc
from .config import canonical
from .activity_engine import require


def routine(item):
    return bool(item and item.get('state_type') not in {'commuting','working','sleeping','eating'}
                and (item.get('intent') == '看电视' or item.get('activity') == 'watch_tv'))


def television(config, place):
    return next((key for key, obj in config['objects'].items()
                 if obj.get('name') == '电视' and obj.get('parent') == place
                 and obj.get('status') == 'confirmed' and obj.get('available', True)), None)


def requirement(cog, state, item, result, at):
    if not television(cog.p.config, item['place']):
        return {**result, 'mode':'blocked', 'reason':'no_catalogued_television_here'}
    ident = 'television:' + item['id']
    plan = state.get('television_sessions', {}).get(ident)
    if not plan: return {**result, 'mode':'needs_detail', 'reason':'call_television_prepare'}
    if plan.get('closed_at'): return {**result, 'mode':'hold', 'reason':'television_session_ended'}
    return {**result, 'mode':'action', 'kind':'television', 'targets':[ident], 'reason':'execute_television_skill'}


def prepare(cog):
    return execute('television.prepare', lambda: _prepare(cog), source='life.television')


def _prepare(cog):
    item = (cog.agenda.view() or {}).get('current_item')
    require(enabled(cog) and routine(item), 'no current television slot')
    device = television(cog.p.config, item['place'])
    require(device, 'no available television at planned place')
    now = cog.clock.now(); ident = 'television:' + item['id']
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE'); state = cog.store.read(db)
        require(state['place'] == item['place'] and state['sleep']['status'] == 'awake', 'arrive awake before television')
        plans = state.setdefault('television_sessions', {})
        if ident in plans: return {'television':plans[ident]}
        require(not state.get('active') and utc(item['end_at']) > now, 'television slot unavailable')
        plan = {'id':ident, 'parent_id':item['id'], 'place':item['place'], 'device':device,
                'end_at':item['end_at'], 'power':'off'}
        plans[ident] = plan; state['revision'] += 1
        db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
    return {'television':plan}


def begin(config, state, activity, at):
    plan = state.get('television_sessions', {}).get(activity['target'])
    require(plan and not plan.get('opened_at') and not plan.get('closed_at') and at < utc(plan['end_at']),
            'television session unavailable or already used')
    require(state['place'] == plan['place'] and television(config, state['place']) == plan['device'],
            'television place/device unavailable')
    plan.update(power='on', opened_at=at.isoformat())
    activity.update(television_mode='events_only', description='左然正在看电视')


def close(state, activity, at):
    if not activity.get('television_mode'): return
    plan = state['television_sessions'][activity['target']]
    if plan.get('closed_at'): return
    plan.update(power='off', closed_at=at.isoformat())
    activity.update(status='completed', completed_at=at.isoformat(), next_due_at=None,
                    description='左然关掉了电视')


def heartbeat(cog):
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE'); state = cog.store.read(db)
        activity = state['activities'].get(state.get('active'))
        if not activity or not activity.get('television_mode'): return False
        now = cog.clock.now()
        if now >= utc(state['television_sessions'][activity['target']]['end_at']):
            cog.p._commit_locked(db, 'television-end:'+activity['id'], {'expected_revision':state['revision'],
                'operation':'interrupt', 'payload':{'activity_id':activity['id'], 'reason':'看电视时段结束'}}, None)
        else:
            activity['next_due_at'] = (now + timedelta(seconds=cog.p.config['checkpoint_seconds'])).isoformat()
            state.update(revision=state['revision']+1, as_of=now.isoformat())
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
    return True
