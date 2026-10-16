"""Shared deterministic facts for planning, chat and read-only status. No model."""
from .work_artifacts import public_task


def progress_view(activity, config):
    if activity.get('work_mode'):
        return {**activity,'progress_unit':'simulated_work_phase_seconds','total':activity['duration_seconds'],
                'target_name':activity['work_title'],'completion_semantics':'phase time only; not case outcome'}
    kind = activity['kind']
    unit = {'reading': 'unicode_code_points', 'moving': 'route_segments',
            'serving': 'route_segments', 'cooking': 'recipe_steps',
            'work': 'validated_work_stages', 'eating': 'portions', 'showering': 'completed_shower'}.get(kind, 'unconfigured')
    total = None
    if activity.get('outing_mode'):
        return {key:value for key,value in {**activity,'target_name':'外出活动'}.items() if key not in {'progress','progress_unit','total'}}
    if activity.get('rest_mode'):
        return {key:value for key,value in {**activity,'target_name':'休息'}.items() if key not in {'progress','progress_unit','total'}}
    if activity.get('television_mode'):
        return {key:value for key,value in {**activity,'target_name':'电视'}.items() if key not in {'progress','progress_unit','total'}}
    if activity.get('exercise_mode'):
        from .skill_exercise import LABELS
        return {**activity,'progress_unit':'active_exercise_seconds','total':activity['duration_seconds'], 'target_name':LABELS[activity['exercise_mode']]}
    if activity.get('housework_mode'):
        return {**activity,'progress_unit':'simulated_housework_seconds','total':activity['duration_seconds'],
                'target_name':activity['housework_title']}
    if activity.get('care_mode'):
        from .skill_personal_care import description
        return {**activity,'progress_unit':'simulated_care_seconds','total':activity['duration_seconds'],
                'target_name':activity['care_title'],'description':description(activity)}
    if activity.get('meal_mode'):
        from .skill_dining import description
        return {**activity,'progress_unit':'simulated_meal_seconds','total':activity['duration_seconds'],
                'target_name':'、'.join(activity['dishes']),'description':'左然'+description(activity)}
    if kind == 'reading':
        from .skill_reading import length
        total = length(config['books'][activity['target']])
        if activity.get('reading_mode') == 'structure_simulation': unit = 'simulated_characters'
    elif kind in {'moving', 'serving'}: total = len(activity['route'])-1
    elif kind == 'cooking': total = len(config['recipes'][activity['target']]['steps'])
    elif kind == 'work': total = len(config['work_items'][activity['target']]['stages'])
    elif kind == 'showering': total = 1
    elif kind == 'watching':
        total = activity.get('movie_duration_seconds') or config['movies'][activity['target']].get('duration_seconds')
        unit = 'simulated_viewing_seconds'
    mapping = None if kind == 'reading' else 'not_applicable'
    if activity.get('reading_mode') == 'structure_simulation':
        from .skill_reading import position
        mapping = position(config['books'][activity['target']], activity['progress'])
    viewing = {}
    if activity.get('viewing_mode') == 'active_time_simulation':
        from .skill_movie import position
        viewing = {'viewing_position': position(total, activity['progress'])}
    return {**activity, **viewing, 'progress_unit': unit, 'total': total,
            'reading_line_page_chapter_paragraph_mapping': mapping}


def unfinished(state, config):
    values = [{'type': 'activity', **progress_view(a, config)} for a in state['activities'].values()
              if a['status'] in {'running', 'interrupted'} and not (config.get('mode') == 'local_single_user' and a['kind'] in {'moving','serving'})]
    values += [{'type': 'work_item', 'id': key, **actual, 'definition': public_task(config['work_items'][key])}
               for key, actual in state.get('work_items', {}).items() if actual['status'] != 'completed' and not config.get('work_skill')]
    values += [{'type': 'commitment', **c} for c in state.get('commitments', []) if c['status'] == 'confirmed']
    for book, content in config.get('books', {}).items():
        offset = state.get('reading', {}).get(book+':'+content['version'], 0)
        from .skill_reading import length
        if isinstance(offset, int) and 0 < offset < length(content) and content.get('available', True):
            values.append({'type': 'reading', 'id': book, 'progress': offset,
                           'progress_unit': 'simulated_characters' if content.get('reading_mode') == 'structure_simulation' else 'unicode_code_points', 'total': length(content)})
    return values


def capabilities(config):
    supported = ['reading', 'cooking', 'eating', 'showering', 'exercising','personal_care', 'housework', 'television', 'rest', 'outing', 'wait']
    if config.get('household_world') and config.get('mode') != 'local_single_user': supported += ['moving', 'serving']
    if config.get('work_items') or config.get('work_skill'): supported += ['work']
    if config.get('movies'): supported += ['watching']
    return {'supported': supported, 'unimplemented': ['inspect_tool', 'repair_tool', 'procure_ingredients', 'drinking'],
        'housework': 'catalog-backed human steps; autonomous simulated washing/cleaning timers; no real device control',
        'test_control_only': ['world_tool'],
        'sleep': 'P3 goodnight input only; natural wake/message wake by committed sleep state; not a P2 action',
        'chat': 'explicit isolated inbox input and local output only; no send capability',
        'wait_effects': [], 'moving_effects': [] if config.get('mode') == 'local_single_user' else ['actual_route_edge_location'],
        'rule': 'Known tool state is evidence, not inspection. Waiting/moving never repair or inspect. Unsupported additional actions must be explicitly rejected.'}
