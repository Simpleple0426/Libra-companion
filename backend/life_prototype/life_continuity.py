"""Durable conversation material derived only from committed life events.

This projection does not create events, change plans or generate memories.
Reading/viewing threads follow a resource across sessions; other threads follow
the actual activity. Private thoughts remain thoughts, never event evidence.
"""
import json

from .config import canonical, digest


RULE = ('生活线来自已提交事件；running才表示正在进行，paused表示暂时放下，completed表示已完成。'
        '阅读和观影进度可跨时段延续；工作阶段结束不等于案件结束。'
        'private_thoughts是已保存的个人想法，不是已发送消息或外部事件。'
        '可以自然分享或继续聊，不必逐项汇报，不把未来安排、作品情节或想法当成真实经历。')


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS life_conversation_threads(
        id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, body TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS life_continuity_cursor(
        id INTEGER PRIMARY KEY CHECK(id=1), event_rowid INTEGER NOT NULL)''')


def _exists(db, name):
    return db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (name,)).fetchone() is not None


def _identity(activity, config):
    kind, target = activity['kind'], activity.get('target')
    if kind in {'reading', 'watching'}:
        resource = config.get('books' if kind == 'reading' else 'movies', {}).get(target, {})
        return 'life-thread:' + digest([kind, target, resource.get('version')])[:32]
    return 'life-thread:' + digest([kind, activity['id']])[:32]


def capture(db, state, config):
    """Incremental, idempotent projection in the caller's life transaction."""
    initialize(db)
    cursor = db.execute('SELECT event_rowid FROM life_continuity_cursor WHERE id=1').fetchone()
    # Existing event history is authoritative too. Bound the initial import.
    start = cursor[0] if cursor else max(0, db.execute('SELECT COALESCE(MAX(rowid),0) FROM events').fetchone()[0] - 500)
    rows = db.execute('SELECT rowid,id,occurred_at,description,kind,activity_id FROM events WHERE rowid>? ORDER BY rowid', (start,)).fetchall()
    for index, event_id, at, description, event_kind, activity_id in rows:
        activity = state.get('activities', {}).get(activity_id)
        if not activity or activity.get('kind') not in {'reading', 'watching', 'work', 'outing', 'cooking', 'eating', 'housework', 'exercising'}:
            continue
        ident = _identity(activity, config)
        old = db.execute('SELECT body FROM life_conversation_threads WHERE id=?', (ident,)).fetchone()
        body = json.loads(old[0]) if old else {'id': ident, 'kind': activity['kind'], 'started_at': activity.get('started_at'), 'milestones': []}
        from .state_view import progress_view
        projected = progress_view(activity, config)
        kind = activity['kind']
        resource = config.get('books' if kind == 'reading' else 'movies' if kind == 'watching' else 'work_items', {}).get(activity.get('target'), {})
        title = projected.get('target_name') or resource.get('title') or resource.get('name') or activity.get('target')
        status = activity.get('status')
        stage = 'running' if state.get('active') == activity_id and status == 'running' else 'paused'
        if status == 'completed':
            stage = 'completed'
        if status in {'failed', 'cancelled'}:
            stage = status
        body.update(activity_id=activity_id, target=activity.get('target'), title=title,
                    stage=stage, updated_at=at, latest_event={'id': event_id, 'kind': event_kind, 'description': description, 'occurred_at': at})
        for key in ('progress', 'total', 'progress_unit', 'reading_line_page_chapter_paragraph_mapping', 'completion_semantics'):
            if projected.get(key) is not None:
                body[key] = projected[key]
        # Keep a small factual history, rather than a new invented story each turn.
        body['milestones'] = (body['milestones'] + [body['latest_event']])[-4:]
        db.execute('INSERT INTO life_conversation_threads VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,body=excluded.body', (ident, at, canonical(body)))
    if rows:
        db.execute('INSERT INTO life_continuity_cursor VALUES(1,?) ON CONFLICT(id) DO UPDATE SET event_rowid=excluded.event_rowid', (rows[-1][0],))


def view(db, state, config, *, limit=5):
    """Read-only and bounded; old threads never establish current activity."""
    threads = []
    if _exists(db, 'life_conversation_threads'):
        # Prefer ongoing material, retaining recent endings for natural follow-up.
        rows = db.execute('''SELECT body FROM life_conversation_threads
            ORDER BY CASE WHEN json_extract(body,'$.activity_id')=? THEN 0
                WHEN json_extract(body,'$.stage') IN ('running','paused') THEN 1 ELSE 2 END,
            updated_at DESC,id LIMIT ?''', (state.get('active'), limit)).fetchall()
        for row in rows:
            body = json.loads(row[0])
            activity = state.get('activities', {}).get(body['activity_id'], {})
            # The snapshot, not the cached event wording, decides "now".
            if body['stage'] == 'running' and (state.get('active') != body['activity_id'] or activity.get('status') != 'running'):
                body['stage'] = 'paused'
            if activity.get('status') in {'completed', 'failed', 'cancelled'}:
                body['stage'] = activity['status']
            body['is_current_activity'] = state.get('active') == body['activity_id'] and activity.get('status') == 'running'
            if activity:
                from .state_view import progress_view
                projected = progress_view(activity, config)
                for key in ('progress', 'total', 'progress_unit', 'reading_line_page_chapter_paragraph_mapping'):
                    if projected.get(key) is not None:
                        body[key] = projected[key]
            threads.append(body)
    thoughts = []
    if _exists(db, 'life_dynamic_drafts'):
        for ident, created_at, raw in db.execute('''SELECT id,created_at,body FROM life_dynamic_drafts
                WHERE kind IN ('leisure_thought','walk_thought')
                AND status IN ('pending_display','displayed','published') ORDER BY created_at DESC LIMIT 4'''):
            draft = json.loads(raw)
            if isinstance(draft.get('body'), str) and draft['body'].strip():
                thoughts.append({'id': ident, 'activity_id': draft.get('activity_id'),
                    'created_at': created_at, 'body': draft['body'][:600], 'semantics': 'private_thought_not_event_or_sent_message'})
    notes = []
    if _exists(db, 'life_quotes'):
        for ident, raw in db.execute('SELECT id,body FROM life_quotes ORDER BY rowid DESC LIMIT 4'):
            note = json.loads(raw)
            notes.append({'id': ident, 'work': note.get('work'), 'thought': note.get('thought', '')[:600],
                          'saved_at': note.get('saved_at'), 'semantics': 'saved_work_impression_not_real_world_event'})
    events = [{'id': row[0], 'occurred_at': row[1], 'description': row[2], 'kind': row[3]}
              for row in db.execute('SELECT id,occurred_at,description,kind FROM events ORDER BY rowid DESC LIMIT 8')]
    return {'threads': threads, 'recent_events': list(reversed(events)), 'private_thoughts': thoughts, 'work_notes': notes, 'rule': RULE}


def record_sent(db, messages):
    """Mailbox bookkeeping for successfully committed chat outputs only."""
    db.execute('''CREATE TABLE IF NOT EXISTS life_sent_conversation(
        id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, body TEXT NOT NULL)''')
    for message in messages:
        if message.get('id') is None or not message.get('content') or not message.get('created_at'):
            continue
        if message.get('message_type', 'text') not in {'text', 'voice'}:
            continue
        body = {key: message.get(key) for key in ('id', 'content', 'created_at', 'source')}
        body['content'] = body['content'][:800]
        body['is_excerpt'] = len(message['content']) > 800
        db.execute('INSERT OR IGNORE INTO life_sent_conversation VALUES(?,?,?)', (str(message['id']), message['created_at'], canonical(body)))
    db.execute('DELETE FROM life_sent_conversation WHERE rowid NOT IN (SELECT rowid FROM life_sent_conversation ORDER BY rowid DESC LIMIT 40)')


def sent_view(db):
    if not _exists(db, 'life_sent_conversation'):
        return []
    return [json.loads(row[0]) for row in reversed(db.execute('SELECT body FROM life_sent_conversation ORDER BY rowid DESC LIMIT 8').fetchall())]
