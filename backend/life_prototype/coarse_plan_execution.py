"""The current saved coarse slot owns action selection, not the model."""
from .clock import utc
from .activity_engine import require
from .coarse_plan import schedule_day


KINDS = {'reading': 'reading', 'watch_movie': 'watching', 'watch_show': 'watching',
         'working': 'work', 'work': 'work', 'home_work': 'work',
         'breakfast': 'eating', 'lunch': 'eating', 'dinner': 'eating',
         'shower': 'showering', 'cooking': 'cooking', 'prepare_meal': 'cooking'}
HOLD = {'resting', 'user_time', 'await_goodnight', 'bedtime_preparation', 'awake_transition'}


def _requirement(cog, state=None, *, db=None, at=None):
    if cog.p.config.get('mode') != 'local_single_user':
        return None
    state = state or cog.p.snapshot()
    at = utc(at or cog.clock.now())
    from .companionship import current, item as companion_item
    companion = current(state, at)
    if companion:
        return {'policy': 'user_led_companionship', 'mode': 'hold', 'reason': 'companion_active',
                'targets': [], 'item': companion_item(companion, at), 'companion': companion,
                'title': companion['title'], 'location_policy': 'unspecified'}
    agenda = cog.agenda._read(db, schedule_day(at)) if db is not None else cog.agenda.read(at)
    item = next((i for i in (agenda or {}).get('items', [])
                 if utc(i['start_at']) <= at < utc(i['end_at'])), None)
    result = {'policy': 'follow_current_coarse_slot', 'agenda_revision': (agenda or {}).get('revision'),
              'item': item, 'mode': 'hold', 'reason': 'no_current_slot', 'targets': []}
    if state.get('sleep', {}).get('status') != 'awake':
        result.update(mode='blocked', reason='not_awake')
        return result
    if not item:
        return result
    if item.get('activity') == 'await_morning':
        result.update(reason='await_confirmed_morning_wake')
        return result
    from .skill_personal_care import routine as care_routine
    from .morning import ready as morning_ready
    if (item.get('intent') == '起床及晨间准备' or care_routine(item) == 'morning_wash') and not morning_ready(state, at):
        result.update(reason='await_confirmed_morning_wake')
        return result
    if item.get('activity') == 'user_time':
        result.update(reason='user_reserved_time', title=item['title'], location_policy='unspecified')
        return result
    if item.get('kind') == 'commute':
        result.update(reason='coarse_commute_in_progress', destination=item.get('coarse_destination') or item.get('destination'))
        return result
    from .skill_router import select,executor
    skill=select(item);handler=executor(cog,item)
    result['skill']=skill
    if handler and skill in {'home_activity','work','dining','housework'}:
        return handler.requirement(cog,state,item,result,at)
    destination = item.get('destination') if item.get('kind') == 'commute' else item.get('place')
    result['destination'] = destination
    state = {**state, 'place': destination}
    if handler:return handler.requirement(cog,state,item,result,at)
    activity = item.get('activity')
    if item.get('kind') == 'commute' or (activity in HOLD and not (item.get('state_type')=='resting' and item.get('intent') not in {None,'','休息'})):
        result.update(reason='at_planned_place' if item.get('kind') == 'commute' else 'reserved_time')
        return result
    from .coarse_plan_schema import detail_kinds
    allowed = detail_kinds(item)
    kind = KINDS.get(activity)
    if kind is None and not allowed:
        result.update(mode='blocked', reason='planned_activity_has_no_executor')
        return result
    result['kind'] = kind
    if allowed:
        from .fine_plan import view, resources
        data = view(cog, state, at=at) or {}
        block = data.get('current_item')
        plans = [p for p in data.get('plans', []) if p['parent_id'] == item['id']]
        if block and block['kind'] in allowed and any(block in p['blocks'] and p['status'] == 'ready' for p in plans):
            result.update(mode='action', kind=block['kind'], targets=[block['target']], reason='execute_saved_fine_block')
        elif not resources(cog, item, state):
            result.update(mode='hold' if item.get('state_type') in {'free', 'leisure'} else 'blocked',
                          reason='no_available_resource_for_planned_state')
        elif plans and plans[-1]['status'] in {'unavailable', 'needs_review', 'retry'}:
            result.update(mode='blocked', reason=plans[-1].get('reason') or 'fine_planning_failed')
        elif plans and plans[-1]['status'] == 'ready' and any(utc(b['start_at']) > at for b in plans[-1]['blocks']):
            result.update(mode='hold', reason='await_saved_fine_block')
        else:
            result.update(mode='needs_detail', reason='call_agenda_prepare')
        return result
    reference = item.get('reference_id')
    if reference and any(a['kind'] == kind and a['target'] == reference and a['status'] == 'completed'
                         for a in state['activities'].values()):
        result.update(mode='hold', reason='planned_activity_completed')
        return result
    if kind == 'eating':
        targets = [key for key, meal in state.get('meals', {}).items()
                   if key == reference and meal.get('remaining', 0) > 0 and meal.get('place') == destination]
    elif kind == 'showering':
        from .daily_obligations import status
        targets = [r['id'] for r in status(cog.p.config, state, at, cog.calendar_provider)
                   if r['id'] == reference and r['status'] == 'due_flexible']
    else:
        targets = [key for key, recipe in cog.p.config.get('recipes', {}).items()
                   if recipe.get('place') == destination and (not reference or key == reference)]
    result.update(mode='action' if targets else 'blocked', targets=targets,
                  reason='execute_planned_activity' if targets else 'planned_resource_unavailable')
    return result


def requirement(cog, state=None, *, db=None, at=None):
    state = state or cog.p.snapshot()
    result = _requirement(cog, state, db=db, at=at)
    # Skills select rooms, but there is no separate movement action or timer.
    for _ in range(3):
        if not result or result.get('kind') != 'moving':
            return result
        destination = result['targets'][0]
        from .coarse_plan_schema import site_id
        item = result.get('item') or {}
        if site_id(destination) != site_id(item.get('place')):
            return {**result, 'mode': 'blocked', 'kind': None, 'targets': [],
                    'reason': 'detail_cannot_change_coarse_location'}
        state = {**state, 'place': destination}
        result = _requirement(cog, state, db=db, at=at)
    raise ValueError('detail location did not converge')


def matches(required, action):
    return bool(required and required['mode'] == 'action' and
                action.get('kind') == required['kind'] and action.get('target') in required['targets'])


def enter_current(cog):
    """Enter an observed scene once, before choosing detailed work there."""
    if cog.p.config.get('mode') != 'local_single_user': return False
    from .config import canonical
    from .event_store import append
    now = cog.clock.now()
    with cog.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state = cog.store.read(db)
        from .companionship import current
        if current(state, now): return False
        if state.get('sleep', {}).get('status') != 'awake': return False
        agenda = cog.agenda._read(db, schedule_day(now))
        item = next((i for i in (agenda or {}).get('items', []) if utc(i['start_at']) <= now < utc(i['end_at'])), None)
        if not item or not item.get('state_type') or item['state_type'] in {'commuting', 'sleeping'}: return False
        if (requirement(cog, state, db=db, at=now) or {}).get('reason') == 'await_confirmed_morning_wake': return False
        user_time = item.get('activity') == 'user_time'
        if not user_time and state['place'] != item['place']: return False
        if (state.get('coarse_state') or {}).get('plan_id') == item['id']: return False
        fact = {'plan_id': item['id'], 'state_type': item['state_type'], 'place': None if user_time else state['place'],
                'start_time': item['start_time'], 'end_time': item['end_time']}
        if user_time:
            fact.update(appointment_id=item['appointment_id'], title=item['title'],
                        source_message=item.get('source_message'),
                        activity='user_time', location_policy='unspecified',
                        semantics='reserved_user_time_started; no user presence or activity outcome inferred')
        state['coarse_state'] = fact
        state['revision'] += 1
        state['as_of'] = now.isoformat()
        ident = 'coarse-state:' + item['id']
        receipt = {'event_id': ident, 'revision': state['revision'], 'occurred_at': now.isoformat(),
                   'recorded_at': now.isoformat(), 'source': 'confirmed_user_reservation' if user_time else 'confirmed_current_location'}
        append(db, ident, {'operation': 'coarse_state', 'fact': fact}, receipt, state, cog.p.config)
        db.execute("UPDATE life_state SET body=? WHERE name='current' AND id=1", (canonical(state),))
        return True


def validate(cog, state, action, *, db=None, at=None):
    required = requirement(cog, state, db=db, at=at)
    if required is None:
        return
    if action['operation'] == 'wait':
        require(required['mode'] in {'hold', 'blocked'}, 'coarse agenda is due; execute it or prepare its fine plan')
    else:
        require(matches(required, action), 'action differs from current coarse agenda; read agenda and follow its execution requirement')


def validate_wait(cog):
    state = cog.p.snapshot()
    required = requirement(cog, state)
    if required is None:
        return None
    active = state['activities'].get(state.get('active'))
    require((active and matches(required, active)) or
            (not active and required['mode'] in {'hold', 'blocked'}),
            'cannot wait past a due coarse action; execute the current plan first')
    return required


def pause_mismatch(cog):
    """Stop an old action at a plan change.

    Books and movies keep a resumable position. Other activities are scoped to
    their current coarse slot and become terminal when that slot changes.
    """
    state = cog.p.snapshot()
    required = requirement(cog, state)
    active = state['activities'].get(state.get('active'))
    if required is None or not active or state.get('sleep', {}).get('status') != 'awake':
        return False
    if matches(required, active):
        return False
    resumable = active.get('kind') in {'reading', 'watching'}
    operation = 'interrupt' if resumable else 'fail'
    # Let the exercise boundary settle through its normal end transition.
    # Running/swimming/shooting finish here; gym check-in still waits for
    # actual departure. A plan replacement before the deadline remains a fail.
    exercise = state.get('exercise_sessions', {}).get(active.get('target'))
    if active.get('exercise_mode') and exercise and utc(cog.clock.now()) >= utc(exercise['end_at']):
        operation = 'interrupt'
    reason = ('粗计划时段或版本已变化；停止旧活动，保留阅读或观影进度' if resumable else
              '粗计划时段或版本已变化；当前活动到此结束，不跨时段保存进度')
    cog.p.command('coarse-boundary:' + str(state['revision']), state['revision'], operation,
                  activity_id=active['id'], reason=reason)
    return True
