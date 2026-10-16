"""Versioned synthetic cases. Expected outcomes never enter model prompts."""
VERSION = 'life-schedule-v3-working-location'
NOW = '2026-09-28T14:00:00+08:00'


def at(time, day='28'):
    return f'2026-09-{day}T{time}:00+08:00'


def turn(text, status='applied', **expected):
    return {'text': text, 'expected': {'status': status, **expected}}


def companion(start=NOW, end=None, **more):
    return {'companion': {'start_at': start, 'end_at': end, **more}}


def item(activity, start='16:00', end='17:00', place=None):
    value = {'activity': activity, 'start_at': at(start), 'end_at': at(end)}
    # The coarse schema stores reading/TV as free time plus explicit intent.
    if activity in {'reading', 'watch_tv'}:
        value.pop('activity')
        value.update(state_type='free', intent={'reading': '阅读', 'watch_tv': '看电视'}[activity])
    if place:
        value['place'] = place
    return {'item': value, 'no_companion': True, 'preserve_required': True}


def case(ident, category, turns, **options):
    return {'id': ident, 'category': category, 'turns': turns, **options}


CASES = [
    case('explicit_now', 'explicit', [turn('现在陪我聊天吧', **companion())]),
    case('explicit_future', 'explicit', [turn('明天下午两点陪我逛漫展', **companion(at('14:00', '29')))]),
    case('explicit_bounded', 'explicit', [turn('今天下午三点陪我聊天，到四点结束', **companion(at('15:00'), at('16:00')))]),
    case('explicit_read', 'explicit', [turn('今天下午四点到五点，你在家里的书房看书吧', **item('reading', place='home.f2.study'))]),
    case('explicit_rest', 'explicit', [turn('今天下午四点到五点，你在家里的客厅休息吧', **item('resting', place='home.f1.living'))]),
    case('explicit_reschedule', 'explicit', [turn('把你今天下午的工作改到四点至五点，其余时间不工作', **item('working'))]),
    case('explicit_cancel', 'explicit', [turn('取消你今天下午的工作，下午不要再工作了', absent_activity='working', no_companion=True, preserve_required=True)]),
    case('explicit_tv', 'explicit', [turn('你今晚八点到九点在家客厅看电视吧', **item('watch_tv', '20:00', '21:00', 'home.f1.living'))]),
    case('vague_invitation', 'clarification', [turn('陪我去漫展吧', 'clarify', unchanged=True)]),
    case('vague_day', 'clarification', [turn('明天陪我逛街吧', 'clarify', unchanged=True)]),
    case('vague_today', 'clarification', [turn('今天陪我看电影吧', 'clarify', unchanged=True)]),
    case('vague_earlier', 'clarification', [turn('今天早点回家吧', 'clarify', unchanged=True)], initial_place='firm.office'),
    case('vague_replace', 'clarification', [turn('把你今天下午的工作改到晚一点吧', 'clarify', unchanged=True)]),
    case('protected_dinner', 'constraint', [turn('取消你今天晚饭的安排，不用吃晚饭了', ['clarify', 'none', 'failed'], unchanged=True)]),
    case('protected_shower', 'constraint', [turn('取消你今晚的洗澡和睡前洗漱安排', ['clarify', 'none', 'failed'], unchanged=True)]),
    case('protected_overlap', 'constraint', [turn('今天下午六点到晚上十点连续在书房看书，期间不要吃饭', ['clarify', 'none', 'failed'], unchanged=True)]),
    case('past_request', 'constraint', [turn('把你今天的工作改到上午十点到十一点', ['clarify', 'none', 'failed'], unchanged=True)]),
    case('unknown_place', 'constraint', [turn('今天下午四点到五点去那个地方看书吧', 'clarify', unchanged=True)]),
    case('chat_greeting', 'no_action', [turn('今天上班辛苦啦', 'none', unchanged=True)]),
    case('chat_self_plan', 'no_action', [turn('我明天可能去看电影，还没决定', 'none', unchanged=True)]),
    case('chat_quote', 'no_action', [turn('同事对别人说“现在陪我去漫展”，我只是转述，不是邀请你', 'none', unchanged=True)]),
    case('chat_negation', 'no_action', [turn('不要改你的日程，我只是问问你今天有什么安排', 'none', unchanged=True)]),
    case('multi_clarify', 'multi_turn', [turn('陪我去漫展吧', 'clarify', unchanged=True),
         turn('明天下午两点开始', **companion(at('14:00', '29')))]),
    case('multi_extend', 'multi_turn', [turn('现在陪我聊天，到下午四点结束', **companion(NOW, at('16:00'))),
         turn('继续陪我到下午五点吧', **companion(NOW, at('17:00')))]),
    case('multi_replace', 'multi_turn', [turn('今天下午四点到五点在书房看书吧', **item('reading')),
         turn('刚才四点到五点的看书改成在客厅休息', **item('resting', place='home.f1.living'), absent_intent='阅读')]),
    case('multi_end', 'multi_turn', [turn('现在陪我聊天吧', **companion()),
         turn('结束陪伴', 'host_ended', no_companion=True)]),
    case('fault_duplicate', 'recovery', [turn('现在陪我聊天吧', **companion())], fault='duplicate'),
    case('fault_restart_queued', 'recovery', [turn('现在陪我聊天吧', **companion())], fault='restart_queued'),
    case('fault_restart_committed', 'recovery', [turn('现在陪我聊天吧', **companion())], fault='restart_committed'),
    case('fault_read_timeout', 'recovery', [turn('现在陪我聊天吧', **companion())], fault='read_timeout'),
]

SMOKE = ['explicit_now', 'vague_invitation', 'chat_greeting', 'multi_clarify', 'fault_duplicate']
