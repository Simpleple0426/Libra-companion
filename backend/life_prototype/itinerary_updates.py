"""User-requested changes to the actor's own itinerary, never companionship."""
from copy import deepcopy
from datetime import timedelta
import re

from .activity_engine import require
from .clock import utc


ACTIVITIES = {
    'home_activity': ('free', '家中活动'), 'resting': ('resting', '休息'),
    'working': ('working', '工作'), 'reading': ('free', '阅读'),
    'watch_movie': ('free', '看电影'), 'watch_tv': ('free', '看电视'),
    'exercising': ('exercising', '运动'), 'housework': ('free', '家务'),
    'outing': ('free', '外出活动'),
}


def _overlaps(a, b, c, d):
    return a < d and c < b


def _item(config, activity, place):
    require(activity in ACTIVITIES and place in config['places'], 'unknown itinerary activity or place')
    broad, intent = ACTIVITIES[activity]
    from .coarse_plan_schema import site_id
    if activity in {'home_activity', 'housework', 'watch_tv'}:
        require(site_id(place) == 'home', 'this activity requires a home location')
    if activity == 'exercising':
        from .skill_exercise import mode
        require(mode(config, place), 'exercise place is unsupported')
    if activity == 'outing':
        require(site_id(place) not in {'home', 'firm'}, 'outing requires a configured outside venue')
    return {'activity': activity, 'state_type': broad, 'kind': {'working': 'work', 'resting': 'rest',
            'exercising': 'exercise'}.get(broad, 'free'), 'intent': intent, 'title': intent,
            'place': place, 'place_name': config['places'][place]['name'], 'semantics': 'planned_not_observed'}


def immediate_itinerary(content):
    """Timing evidence for personal itinerary only; companionship is separate."""
    if re.search(r'明天|后天|下周|如果|假如|要是|不要|别|不用|不必|了吗|了么|几点|什么时候|[？?]|说过|他说|她说|[“”「」]', content):
        return False
    return bool(re.search(r'(?:现在|马上|立即|这就|赶紧|快点)(?:就)?(?:回家|出发|下班|开始|去|在|看|休息|把)', content)
                or re.fullmatch(r'[\s，,！!。]*(?:急[\s，,！!。]*)*(?:你)?(?:快|赶紧|快点)?回家(?:吧|呀|啊|啦)?[\s，,！!。]*', content))


def validate(changes, body, state, config, now, message):
    from .coarse_plan import _at, schedule_day
    from .coarse_plan_updates import protected
    from .companionship import _start_time_evidence
    end_day = _at(schedule_day(now) + timedelta(days=1), '04:00')
    items = {i['id']: i for i in body['items']}
    result = []
    for change in changes:
        require(isinstance(change, dict) and set(change) == {
            'operation', 'item_id', 'start_at', 'end_at', 'activity', 'place_id'}, 'invalid itinerary change')
        op = change['operation']
        require(op in {'cancel', 'replace', 'reschedule', 'return_home'}, 'unknown itinerary operation')
        original = items.get(change['item_id']) if change['item_id'] else None
        if op in {'cancel', 'reschedule'}:
            require(original and not protected(original) and original['kind'] != 'commute'
                    and not original.get('appointment_id') and utc(original['end_at']) > now,
                    'cannot cancel/reschedule a past, required, travel or appointment item')
            result.append({'operation': 'cancel', 'start_at': max(now, utc(original['start_at'])).isoformat(),
                           'end_at': original['end_at'], 'source_message': message['id']})
        else:
            require(change['item_id'] is None, 'replace/return_home uses a time window, not an item ID')
        if op == 'cancel':
            require(all(change[k] is None for k in ('start_at', 'end_at', 'activity', 'place_id')),
                    'cancel must not contain replacement fields')
            continue
        # The semantic interpreter must ask for a concrete time instead of
        # silently assigning one to "早点". Current-message evidence also
        # supports the user's follow-up answer after that clarification.
        immediate = immediate_itinerary(message['content'])
        timing_text = re.sub(r'(改|调整|推迟|提前|挪|换)到', r'\1为', message['content'])
        # A delivered actor commitment may select its own feasible time. It is
        # never evidence of user consent to companionship or an appointment.
        actor_choice = bool(message.get('assistant_replies'))
        require(immediate or actor_choice or (change['start_at'] is not None and
                _start_time_evidence(timing_text, immediate=False)),
                '请先确认具体调整时间；不能把“早点”自行解释成某个时间')
        if immediate:
            change = {**change, 'start_at': None}  # resolve at commit, not model-call start
        if change['start_at'] is None:
            require(schedule_day(utc(message['received_at'])) == schedule_day(now), 'stale immediate itinerary request')
        start = utc(change['start_at']) if change['start_at'] else now
        end = end_day if op == 'return_home' else utc(change['end_at']) if change['end_at'] else None
        require(end is not None and now <= start < end <= end_day, 'itinerary edit must fit the remaining living day')
        if op == 'return_home':
            require(all(change[k] is None for k in ('activity', 'place_id', 'end_at')),
                    'return_home uses departure time and keeps remaining life at home')
            core = _item(config, 'home_activity', 'home.f1.living')
        elif op == 'reschedule':
            require(change['activity'] is None and change['place_id'] is None, 'reschedule preserves activity and place')
            core = deepcopy(original)
        else:
            core = _item(config, change['activity'], change['place_id'])
        if op != 'return_home':
            require(all(not protected(i) or not _overlaps(start, end, utc(i['start_at']), utc(i['end_at']))
                        for i in body['items']), '新活动时间与必要用餐或洗漱冲突，请重新协商')
            core['itinerary_fixed'] = True
        result.append({'operation': op, 'start_at': start.isoformat(), 'end_at': end.isoformat(),
                       'item': core, 'source_message': message['id']})
    for edit in result:
        start, end = utc(edit['start_at']), utc(edit['end_at'])
        for session in state.get('companionships', []):
            if session['status'] == 'ended': continue
            finish = utc(session['end_at']) if session['end_at'] else end_day
            require(not _overlaps(start, end, utc(session['start_at']), finish),
                    '行程调整与已确认陪伴冲突；请先协商结束或改期陪伴')
        for appointment in body.get('user_constraints', {}).get('appointments', []):
            require(not _overlaps(start, end, utc(appointment['start_at']), utc(appointment['end_at'])),
                    '行程调整与已有预约冲突；请先协商取消或改期预约')
        for commitment in state.get('commitments', []):
            if commitment.get('status') == 'confirmed':
                require(not start <= utc(commitment['due_at']) < end,
                        '行程调整涉及已确认约定；请先协商，不能直接覆盖')
    return result


def apply(body, edits, state, config, now):
    """Overlay only soft intentions; let the existing reflow build travel."""
    from .coarse_plan_updates import protected
    from .coarse_plan_schema import site_id
    revised = deepcopy(body)
    for edit in edits:
        left, right = max(now, utc(edit['start_at'])), utc(edit['end_at'])
        if right <= left: continue
        kept, occupied = [], []
        for original in revised['items']:
            start, end = utc(original['start_at']), utc(original['end_at'])
            if original['kind'] == 'commute' and end > now:
                continue  # Reflow rebuilds routes from verified physical state.
            if not _overlaps(left, right, start, end):
                kept.append(original)
                continue
            if original.get('appointment_id'):
                raise ValueError('行程调整不能覆盖用户预约')
            if protected(original):
                original = deepcopy(original)
                if edit['operation'] == 'return_home' and site_id(original['place']) != 'home':
                    require(original['kind'] == 'meal', 'required activity cannot be relocated')
                    ref = original.get('reference_id')
                    prepared = state.get('meal_plans', {}).get(ref)
                    require(not prepared or prepared.get('completed_at'), '已有准备中的餐食，请先完成或协商后再回家')
                    require(ref not in state.get('meals', {}) or state['meals'][ref].get('remaining', 0) == 0,
                            '已有餐食资源不能自动搬到家中')
                    original['place'] = config['household_world']['dining_place']
                    original['place_name'] = config['places'][original['place']]['name']
                    # Packed room hints must agree with the new meal location.
                    original.setdefault('constraints', {}).pop('execution_location_id', None)
                    original['constraints'].pop('execution_location_name', None)
                occupied.append((max(left, start), min(right, end)))
                kept.append(original)
                continue
            if start < left:
                kept.append({**deepcopy(original), 'end_at': left.isoformat()})
            if right < end:
                kept.append({**deepcopy(original), 'start_at': right.isoformat()})
        if edit['operation'] != 'cancel':
            fragments = [(left, right)]
            for a, b in occupied:
                fragments = [(x, y) for start, end in fragments
                             for x, y in ((start, min(end, a)), (max(start, b), end)) if x < y]
            for start, end in fragments:
                kept.append({**deepcopy(edit['item']), 'id': 'itinerary:' + edit['source_message'],
                             'start_at': start.isoformat(), 'end_at': end.isoformat(),
                             'source_message': edit['source_message']})
        revised['items'] = sorted(kept, key=lambda i: utc(i['start_at']))
    return revised


def check_result(body, edits, now):
    """Do not report an applied edit if travel/obligations made it disappear."""
    from .coarse_plan_schema import site_id
    for edit in edits:
        if edit['operation'] == 'cancel': continue
        start, end = max(now, utc(edit['start_at'])), utc(edit['end_at'])
        if start >= end: continue
        matches = [i for i in body['items'] if i.get('source_message') == edit['source_message']
                   and i.get('activity') == edit['item']['activity'] and
                   _overlaps(start, end, utc(i['start_at']), utc(i['end_at']))]
        require(matches, '调整后没有足够时间执行所选活动，请重新协商时间')
        if edit['operation'] != 'return_home':
            require(any(utc(i['start_at']) == start and utc(i['end_at']) == end for i in matches),
                    '无法完整保留已确认活动时段，请重新协商')
        if edit['operation'] == 'return_home':
            departures = [i for i in body['items'] if i['kind'] == 'commute'
                          and site_id(i.get('destination')) == 'home' and utc(i['end_at']) > start]
            require(not departures or utc(departures[0]['start_at']) == start,
                    '必要活动或通勤与回家出发时间冲突，请重新协商')
