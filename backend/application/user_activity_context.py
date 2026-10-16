"""Small timestamped activity background, independent of contact permission."""
from datetime import timedelta
import json
from domains.world.time_boundary import local_time
from application.diary_context import event_time


def charging(description):
    return any(word in str(description) for word in ('手机开始充电', '手机结束充电', '手机正在充电'))


def recent(events, now=None):
    now = local_time(now)
    rows = []
    for event in events:
        at = event_time(event.get('occurred_at'))
        if at is None or not now - timedelta(hours=24) <= at <= now or charging(event.get('description')):
            continue
        rows.append({'occurred_at': at.isoformat(), 'source': event.get('event_type') or 'legacy',
                     'description': str(event.get('description') or '')[:240]})
    rows.sort(key=lambda e: (e['source'] == 'manual_timeline', e['occurred_at']), reverse=True)
    return sorted(rows[:8], key=lambda e: e['occurred_at'])


def block(events):
    if not events:
        return ''
    return ('\n<recent_user_activity>\n' + json.dumps(events, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e')
            + '\n</recent_user_activity>\n这是用户近期首页活动，不是本轮聊天原话，也不是待办计划。'
            '按发生时间理解，开始记录不证明现在仍持续，未记录结束也不证明仍在进行；'
            '优先结合后续消息与最新记录，不确定时自然确认。无需复述来源或逐项报动态。\n')
