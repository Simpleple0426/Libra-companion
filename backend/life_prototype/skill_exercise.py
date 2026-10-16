"""Minimal exercise sessions without detailed training content."""
from datetime import timedelta
from application.content_tools import execute
from .clock import utc
from .config import canonical
from .activity_engine import require
from .skill_personal_care import enabled

LABELS = {'running':'跑步', 'gym':'健身', 'swimming':'游泳', 'shooting':'射击'}


def event_text(exercise_mode, *, ending=False):
    if exercise_mode == 'gym':
        return '左然结束健身，离开健身房，完成运动打卡' if ending else '左然到达健身房，开始健身'
    return '左然'+('结束' if ending else '开始')+LABELS[exercise_mode]+('，完成运动打卡' if ending and exercise_mode=='running' else '')


def routine(item):
    return bool(item and item.get('state_type') != 'commuting' and
                (item.get('state_type') == 'exercising' or item.get('intent') == '运动' or item.get('activity') in {'exercising','swimming','shooting'}))


def mode(config, place):
    if place.startswith('home.'):
        return 'running' if any(o.get('name') == '跑步机' and o.get('parent') == place and
                               o.get('available', True) and o.get('status') == 'confirmed'
                               for o in config['objects'].values()) else None
    venue = config['places'].get(place, {})
    if venue.get('exercise_mode') in {'gym','swimming','shooting'}: return venue['exercise_mode']
    return next((kind for word, kind in [('健身房','gym'),('游泳馆','swimming'),('射击馆','shooting')]
                 if word in venue.get('name','')), None)


def requirement(cog, state, item, result, at):
    if not mode(cog.p.config, item['place']):
        return {**result, 'mode':'blocked', 'reason':'exercise_place_not_supported'}
    ident = 'exercise:' + item['id']
    plan = state.get('exercise_sessions', {}).get(ident)
    if not plan: return {**result, 'mode':'needs_detail', 'reason':'call_exercise_prepare'}
    if plan.get('completed_at'): return {**result, 'mode':'hold', 'reason':'exercise_completed'}
    return {**result, 'mode':'action', 'kind':'exercising', 'targets':[ident], 'reason':'execute_exercise_skill'}


def prepare(cog):
    return execute('exercise.prepare', lambda: _prepare(cog), source='life.exercise')


def _prepare(cog):
    item = (cog.agenda.view() or {}).get('current_item')
    require(enabled(cog) and routine(item), 'no current exercise slot')
    exercise_mode = mode(cog.p.config, item['place'])
    require(exercise_mode, 'exercise requires a local treadmill or configured sports venue')
    now = cog.clock.now(); ident = 'exercise:' + item['id']
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE'); state = cog.store.read(db)
        require(state['place'] == item['place'] and state['sleep']['status'] == 'awake', 'arrive awake before exercise')
        plans = state.setdefault('exercise_sessions', {})
        if ident in plans: return {'exercise':plans[ident]}
        require(not state.get('active') and utc(item['end_at']) > now, 'exercise slot unavailable')
        plan = {'id':ident, 'parent_id':item['id'], 'place':item['place'], 'mode':exercise_mode,
                'end_at':item['end_at'], 'progress':0, 'created_at':now.isoformat()}
        plans[ident] = plan; state['revision'] += 1
        db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
    return {'exercise':plan}


def begin(config, state, activity, at):
    plan = state.get('exercise_sessions', {}).get(activity['target'])
    require(plan and not plan.get('completed_at') and at < utc(plan['end_at']), 'exercise session missing or ended')
    require(state['place'] == plan['place'] and mode(config, state['place']) == plan['mode'], 'exercise place unavailable')
    require(not any(a['id'] != activity['id'] and a.get('exercise_mode') and a['target'] == plan['id']
                    and a['status'] in {'running','interrupted'} for a in state['activities'].values()), 'resume existing exercise')
    plan.setdefault('started_at', at.isoformat())
    activity.update(exercise_mode=plan['mode'], progress=plan['progress'], heartbeat_at=at.isoformat(),
                    duration_seconds=max(1, (utc(plan['end_at']) - at).total_seconds() + plan['progress']),
                    description='左然正在'+('健身房健身' if plan['mode']=='gym' else LABELS[plan['mode']]))


def settle(config, state, activity, at, *, recovering=False):
    if not activity.get('exercise_mode') or activity['status'] != 'running': return
    plan = state['exercise_sessions'][activity['target']]
    previous = utc(activity['heartbeat_at'])
    seconds = max(0, (min(at, utc(plan['end_at'])) - previous).total_seconds())
    if recovering or (at - previous).total_seconds() > 90 or state['place'] != activity['place']: seconds = 0
    activity['progress'] += seconds; plan['progress'] = activity['progress']
    activity.update(heartbeat_at=at.isoformat(), last_progress_at=at.isoformat(), revision=activity['revision']+1)


def finish(state, activity, at):
    plan = state['exercise_sessions'][activity['target']]
    if plan.get('completed_at') or activity['progress'] <= 0: return
    plan['completed_at'] = at.isoformat()
    activity.update(status='completed', completed_at=at.isoformat(), next_due_at=None)
    from .coarse_plan import schedule_day
    state.setdefault('exercise_checkins', {})[plan['id']] = {
        'id':plan['id'], 'date':str(schedule_day(utc(plan['started_at']))), 'place':plan['place'],
        'mode':plan['mode'], 'started_at':plan['started_at'], 'ended_at':at.isoformat(),
        'active_seconds':activity['progress'], 'source':'active_time_simulation'}


def departure(state, moving, at):
    ended = []
    for activity in state['activities'].values():
        if activity.get('exercise_mode') and activity['place'] == state['place'] and activity['status'] == 'interrupted':
            finish(state, activity, at)
            if activity['status'] == 'completed': ended.append(activity['id'])
    moving['exercise_departures'] = ended


def heartbeat(cog):
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE'); state = cog.store.read(db)
        activity = state['activities'].get(state.get('active'))
        if not activity or not activity.get('exercise_mode'): return False
        now = cog.clock.now(); settle(cog.p.config, state, activity, now)
        activity['next_due_at'] = (now + timedelta(seconds=cog.p.config['checkpoint_seconds'])).isoformat()
        state.update(revision=state['revision']+1, as_of=now.isoformat())
        db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        if now >= utc(state['exercise_sessions'][activity['target']]['end_at']):
            cog.p._commit_locked(db, 'exercise-boundary:'+activity['id'], {'expected_revision':state['revision'],
                'operation':'interrupt', 'payload':{'activity_id':activity['id'], 'reason':'运动时段结束'}}, None)
    return True
