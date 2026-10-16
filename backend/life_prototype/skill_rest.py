"""Simple awake rest lifecycle; explicit activity intents take precedence."""
from datetime import timedelta
from application.content_tools import execute
from .skill_personal_care import enabled
from .clock import utc
from .config import canonical
from .activity_engine import require


def routine(item):
    if not item or item.get('state_type') in {'commuting','working','eating','exercising','sleeping'}: return False
    if (item.get('constraints') or {}).get('required_routine'): return False
    intent = item.get('intent')
    if intent: return intent in {'休息','午休'}
    if item.get('activity') not in {None,'free','resting','short_break'}: return False
    return item.get('state_type') == 'resting' or item.get('activity') in {'resting','short_break'}


def requirement(cog, state, item, result, at):
    ident = 'rest:' + item['id']
    plan = state.get('rest_sessions', {}).get(ident)
    if not plan: return {**result, 'mode':'needs_detail', 'reason':'call_rest_prepare'}
    if plan.get('closed_at'): return {**result, 'mode':'hold', 'reason':'rest_session_ended'}
    return {**result, 'mode':'action', 'kind':'rest', 'targets':[ident], 'reason':'execute_rest_skill'}


def prepare(cog):
    return execute('rest.prepare', lambda: _prepare(cog), source='life.rest')


def _prepare(cog):
    item = (cog.agenda.view() or {}).get('current_item')
    require(enabled(cog) and routine(item), 'no current rest slot')
    now = cog.clock.now(); ident = 'rest:' + item['id']
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE'); state = cog.store.read(db)
        require(state['place'] == item['place'] and state['sleep']['status'] == 'awake', 'arrive awake before rest')
        plans = state.setdefault('rest_sessions', {})
        if ident in plans: return {'rest':plans[ident]}
        require(not state.get('active') and utc(item['end_at']) > now, 'rest slot unavailable')
        plan = {'id':ident, 'parent_id':item['id'], 'place':item['place'],
                'end_at':item['end_at']}
        plans[ident] = plan; state['revision'] += 1
        db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
    return {'rest':plan}


def begin(config, state, activity, at):
    plan = state.get('rest_sessions', {}).get(activity['target'])
    require(plan and not plan.get('opened_at') and not plan.get('closed_at') and at < utc(plan['end_at']),
            'rest session unavailable or already used')
    require(state['place'] == plan['place'] and state['sleep']['status'] == 'awake',
            'rest requires the planned place and awake state')
    plan.update(opened_at=at.isoformat())
    activity.update(rest_mode='events_only', description='左然正在休息')


def close(state, activity, at):
    if not activity.get('rest_mode'): return
    plan = state['rest_sessions'][activity['target']]
    if plan.get('closed_at'): return
    plan.update(closed_at=at.isoformat())
    activity.update(status='completed', completed_at=at.isoformat(), next_due_at=None,
                    description='左然结束了休息')


def heartbeat(cog):
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE'); state = cog.store.read(db)
        activity = state['activities'].get(state.get('active'))
        if not activity or not activity.get('rest_mode'): return False
        now = cog.clock.now()
        if now >= utc(state['rest_sessions'][activity['target']]['end_at']):
            cog.p._commit_locked(db, 'rest-end:'+activity['id'], {'expected_revision':state['revision'],
                'operation':'interrupt', 'payload':{'activity_id':activity['id'], 'reason':'休息时段结束'}}, None)
        else:
            activity['next_due_at'] = (now + timedelta(seconds=cog.p.config['checkpoint_seconds'])).isoformat()
            state.update(revision=state['revision']+1, as_of=now.isoformat())
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
    return True
