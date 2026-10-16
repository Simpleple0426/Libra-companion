"""Persist coarse plans in the legacy time/state/location vocabulary."""
from copy import deepcopy

VERSION = 'skill-coarse-v13-flexible-evening-shower'
TYPES = {'commuting', 'working', 'eating', 'exercising', 'resting', 'free', 'sleeping'}


def site_id(place):
    """Return the location level used by the coarse agenda."""
    if not place: return place
    if place == 'home' or str(place).startswith('home.'): return 'home'
    if place == 'firm' or str(place).startswith('firm.'): return 'firm'
    return place


def site_name(place, fallback=''):
    return {'home': '家', 'firm': '忒弥斯律所'}.get(site_id(place), fallback)

# Broad preferences, never resource IDs or permission to complete an activity.
INTENTS = {
    'working': '工作', 'work': '工作', 'home_work': '工作',
    'reading': '阅读', 'watch_movie': '看电影', 'watch_tv': '看电视', 'watch_show': '娱乐', 'leisure': '娱乐',
    'prepare_meal': '备餐', 'breakfast': '用餐', 'lunch': '用餐', 'dinner': '用餐',
    'clean_dishes': '家务', 'tidy': '家务', 'housework': '家务',
    'household_tidy': '家务', 'laundry': '家务', 'dry_laundry': '家务',
    'wash': '洗漱', 'morning_wash': '洗漱', 'bedtime_wash': '洗漱',
    'shower': '洗澡', 'bedtime_preparation': '准备睡觉', 'await_goodnight': '准备睡觉',
    'exercising': '运动', 'swimming': '运动', 'shooting': '运动', 'resting': '休息', 'short_break': '休息',
    'short_purchase': '外出办事', 'outing': '外出活动', 'short_leisure': '娱乐',
    'user_time': '陪伴交流',
}


def intent(item):
    if 'intent' in item:
        return item['intent']
    activity = item.get('constraints', {}).get('required_routine') or item.get('activity')
    place = item.get('place_name', item.get('from_location'))
    # Location supplies a preference; explicit routines and adapted movies survive.
    if state_type(item) == 'free':
        if place == '影音区' and activity in {None, 'free', 'leisure', 'watch_movie', 'watch_show'}:
            return '看电影'
        if (place == '客厅' or item.get('place', item.get('location_id')) == 'home.f1.living') and activity in {None, 'free', 'leisure', 'watch_tv'}:
            return '看电视'
    return INTENTS.get(activity, {'working': '工作', 'eating': '用餐',
        'exercising': '运动', 'resting': '休息'}.get(state_type(item)))


def state_type(item):
    if item.get('state_type') == 'leisure': return 'free'
    if item.get('state_type') in TYPES:
        return item['state_type']
    if item.get('kind') == 'commute': return 'commuting'
    if item.get('kind') == 'meal': return 'eating'
    if item.get('legacy_state_type') == 'leisure': return 'free'
    if item.get('legacy_state_type') in TYPES: return item['legacy_state_type']
    return {'work': 'working', 'leisure': 'free', 'rest': 'resting'}.get(item.get('kind'), 'free')


def pack_item(item):
    """No book, movie, or detailed activity is selected by a coarse row."""
    broad = state_type(item)
    if item.get('activity') in {'bedtime_preparation', 'await_goodnight'} or item.get('constraints', {}).get('required_routine') in {'bedtime_preparation', 'await_goodnight'}:
        broad = 'free'
    constraints = deepcopy(item.get('constraints', {}))
    execution_place = item.get('place', item.get('location_id'))
    execution_destination = item.get('destination', item.get('destination_id'))
    coarse_place = site_id(execution_place)
    coarse_destination = site_id(execution_destination)
    if execution_place and execution_place != coarse_place:
        constraints['execution_location_id'] = execution_place
        constraints['execution_location_name'] = item.get('place_name', item.get('from_location', ''))
    if broad == 'commuting' and execution_destination and execution_destination != coarse_destination:
        constraints['execution_destination_id'] = execution_destination
        constraints['execution_destination_name'] = item.get('destination_name', item.get('end_location', ''))
    for key in ('reference_id', 'appointment_id', 'source_message', 'location_policy', 'itinerary_fixed'):
        if item.get(key) is not None: constraints[key] = item[key]
    if item.get('activity') == 'user_time' or constraints.get('required_routine') == 'user_time':
        constraints['appointment_title'] = item.get('appointment_title') or item.get('title') or item.get('intent') or '陪用户'
        constraints['location_policy'] = 'unspecified'
        execution_place = coarse_place = None
        constraints.pop('execution_location_id', None)
        constraints.pop('execution_location_name', None)
    if item.get('activity') in {'shower', 'bedtime_wash', 'bedtime_preparation', 'await_goodnight', 'await_morning', 'user_time'}:
        constraints['required_routine'] = item['activity']
    if item.get('activity') in {'clean_dishes','laundry','dry_laundry','fold_laundry','household_tidy','housework','tidy'}:
        constraints['housework_routine']=item['activity']
    if item.get('activity')=='home_activity': constraints['home_activity']=True
    result = {'id': item['id'], 'start_time': item.get('start_at', item.get('start_time')),
              'end_time': item.get('end_at', item.get('end_time')), 'state_type': broad, 'intent': intent(item),
              'from_location': '' if constraints.get('required_routine') == 'user_time' else site_name(coarse_place, item.get('place_name', item.get('from_location', ''))),
              'end_location': site_name(coarse_destination, item.get('destination_name', item.get('end_location', ''))) if broad == 'commuting' else '',
              'location_id': coarse_place,
              'destination_id': coarse_destination if broad == 'commuting' else None}
    if item.get('coarse_intent'): result['coarse_intent']=item['coarse_intent']
    if constraints: result['constraints'] = constraints
    # Stable cancellation identity is about a state window, not a chosen book.
    legacy_identity = [item.get(k) for k in ('legacy_activity', 'legacy_place', 'legacy_start_at', 'legacy_end_at')]
    result['source_window'] = item.get('source_window') or (legacy_identity if any(legacy_identity) else
        [broad, result['location_id'], result['start_time'], result['end_time']])
    return result


def unpack_item(item):
    if 'state_type' not in item or 'start_time' not in item:
        return deepcopy(item)  # Previous revisions remain readable.
    result = deepcopy(item)
    broad = state_type(item)
    result['state_type'] = broad
    constraints = item.get('constraints', {})
    activity = {'working': 'working', 'eating': 'eating', 'resting': 'resting',
                'free': 'free', 'sleeping': 'await_goodnight',
                'exercising': 'exercising', 'commuting': 'moving'}[broad]
    activity = constraints.get('required_routine', constraints.get('housework_routine',activity))
    if constraints.get('home_activity'): activity='home_activity'
    if broad == 'eating' and constraints.get('reference_id'):
        activity = constraints['reference_id'].rsplit(':', 1)[-1]
    kind = {'commuting': 'commute', 'working': 'work', 'eating': 'meal', 'resting': 'rest',
            'sleeping': 'bedtime', 'exercising': 'exercise'}.get(broad, broad)
    if activity == 'shower': kind = 'shower'
    if activity == 'user_time': kind = 'interaction'
    if activity in {'bedtime_wash', 'bedtime_preparation', 'await_goodnight'}: kind = 'bedtime'
    titles = {'commuting': '前往' + item['end_location'], 'working': '工作', 'eating': '用餐',
              'resting': '休息', 'free': '自由安排', 'sleeping': '睡眠安排', 'exercising': '运动'}
    execution_place = constraints.get('execution_location_id', item['location_id'])
    execution_name = constraints.get('execution_location_name', item['from_location'])
    result.update(start_at=item['start_time'], end_at=item['end_time'], place=execution_place,
                  place_name=execution_name, coarse_place=item['location_id'],
                  coarse_place_name=item['from_location'], kind=kind, activity=activity, title=titles[broad],
                  execution='coarse_state_then_fine_plan', semantics='planned_not_observed', **constraints)
    if activity == 'user_time':
        from .appointments import display_title
        title = display_title(constraints.get('appointment_title') or item.get('intent') or '陪用户')
        result.update(title=title, intent=title, place=None, place_name='', coarse_place=None,
                      coarse_place_name='', location_policy='unspecified', execution='reserved_user_time')
    if broad == 'commuting':
        result.update(destination=constraints.get('execution_destination_id', item['destination_id']),
                      destination_name=constraints.get('execution_destination_name', item['end_location']),
                      coarse_destination=item['destination_id'], coarse_destination_name=item['end_location'])
    return result


def pack(body):
    result = deepcopy(body)
    result['version'] = VERSION
    for key in ('items', 'past_items'):
        if key in result: result[key] = [pack_item(i) for i in result[key]]
    return result


def unpack(body):
    result = deepcopy(body)
    for key in ('items', 'past_items'):
        if key in result: result[key] = [unpack_item(i) for i in result[key]]
    return result


def detail_kinds(parent):
    from .skill_outing import routine as outing_routine
    if outing_routine(parent): return set()
    from .skill_rest import routine as rest_routine
    if rest_routine(parent): return set()
    from .skill_television import routine as tv_routine
    if tv_routine(parent): return set()
    from .skill_exercise import routine as exercise_routine
    if exercise_routine(parent): return set()
    from .skill_housework import routine as housework_routine
    if housework_routine(parent): return set()
    from .skill_personal_care import routine
    if routine(parent): return set()
    if parent.get('constraints', {}).get('required_routine'): return set()
    broad = state_type(parent) if parent.get('state_type') is not None else None
    if broad == 'resting':
        specific = {'阅读':'reading','看电影':'watching','工作':'work'}.get(parent.get('intent'))
        if specific: return {specific}
        legacy = {'reading':'reading','watch_movie':'watching','watch_show':'watching'}.get(parent.get('activity'))
        return {legacy} if legacy and not parent.get('intent') else set()
    if broad is not None:
        return {'working': {'work'},
                'free': {'reading', 'watching', 'work'}}.get(broad, set())
    kind = {'reading': 'reading', 'watch_movie': 'watching', 'watch_show': 'watching',
            'working': 'work', 'work': 'work', 'home_work': 'work'}.get(parent.get('activity'))
    return {kind} if kind else set()
