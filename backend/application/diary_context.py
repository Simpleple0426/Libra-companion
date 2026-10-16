"""Read-only daily evidence for private diary generation."""
from datetime import datetime, timedelta

from domains.world.time_boundary import local_time


def event_time(value):
    try:
        return local_time(datetime.fromisoformat(str(value).replace('Z', '+00:00')))
    except (TypeError, ValueError):
        return None


def life_events(life_mode, start, end):
    """Use committed life facts, including the early hours of a living day."""
    day = start.date() - timedelta(days=1)
    rows = {}
    while day <= end.date():
        for item in life_mode.activity_feed(schedule_date=day, limit=None):
            at = event_time(item.get('occurred_at'))
            detail = item.get('detail') or {}
            if at is None or not start <= at < end:
                continue
            if item.get('kind') == 'agenda_changed' or detail.get('fact_basis') == 'committed_agenda_revision':
                continue
            text = str(item.get('event') or '').strip()
            if text:
                rows[(at, str(item.get('id') or text))] = (at, text, detail.get('semantics'))
        day += timedelta(days=1)
    lines = []
    for at, text, semantics in sorted(rows.values(), key=lambda row: (row[0], row[1])):
        if semantics:
            text += f'（事实边界：{semantics}）'
        lines.append(f'{at:%m-%d %H:%M} {text}')
    return '\n'.join(lines) or '当天没有留下已确认的生活活动记录。'


def chat_transcript(messages, budget=14000):
    labels = {'movie_chat': '影音室对话', 'music_room': '音乐房对话',
              'movie_watch': '共同观影时的发言'}
    entries = []
    for item in messages:
        content = str(item.get('content') or '').strip()
        if not content:
            continue
        at = event_time(item.get('created_at'))
        role = '用户' if item.get('role') == 'user' else '左然'
        source = labels.get(item.get('source'))
        prefix = f'{at:%m-%d %H:%M}' if at else '时间未知'
        entries.append(f'{prefix} {role}' + (f'（{source}）' if source else '') + f'：{content}')
    if not entries:
        return '这一天没有留下聊天记录。'
    # Keep evidence from throughout the day instead of only the last conversation.
    omitted = False
    max_entries = max(2, budget // 120)
    if len(entries) > max_entries:
        entries = [entries[index * (len(entries) - 1) // (max_entries - 1)]
                   for index in range(max_entries)]
        omitted = True
    allowance = max(1, budget // len(entries) - 2)
    shortened = [line if len(line) <= allowance else line[:allowance] + '…' for line in entries]
    text = '\n'.join(shortened)
    if len(text) > budget:
        text = text[:budget] + '\n（聊天资料过长，部分内容省略。）'
    elif omitted:
        text += '\n（聊天资料过长，部分消息已省略，不得补写省略内容。）'
    elif shortened != entries:
        text += '\n（部分长消息已截短，不得补写省略内容。）'
    return text
