"""Persistent chat arrangements and due reminders backed by the todo records."""
from datetime import datetime, timedelta
import json
import hashlib
from domains.world.time_boundary import local_time


def initialize(c):
    # DDL is not automatically routed; cognition connections attach core.
    schemas = {r[1] for r in c.execute('PRAGMA database_list')}
    schema = 'core' if 'core' in schemas else 'main'
    c.execute(f'''CREATE TABLE IF NOT EXISTS {schema}.todo_reminders (
        local_id TEXT PRIMARY KEY, remind_at TEXT, repeat_rule TEXT,
        revision INTEGER NOT NULL DEFAULT 1, delivered_at TEXT,
        lease_until TEXT, deleted INTEGER NOT NULL DEFAULT 0)''')
    c.execute(f'CREATE INDEX IF NOT EXISTS {schema}.idx_reminders_due ON todo_reminders(remind_at)')


def settings(c, item):
    initialize(c)
    previous = c.execute('SELECT * FROM todo_reminders WHERE local_id=?', (item['local_id'],)).fetchone()
    if previous and previous['deleted']:
        return False
    if 'remind_at' not in item:
        return True  # Old clients preserve reminder settings.
    at = item.get('remind_at')
    at = local_time(datetime.fromisoformat(at.replace('Z', '+00:00'))).isoformat() if at else None
    repeat = None  # Only one-off reminders are supported.
    if previous and previous['remind_at'] == at and previous['repeat_rule'] == repeat:
        return True
    c.execute('''INSERT INTO todo_reminders(local_id,remind_at,repeat_rule) VALUES(?,?,?)
        ON CONFLICT(local_id) DO UPDATE SET remind_at=excluded.remind_at,
        repeat_rule=excluded.repeat_rule,revision=revision+1,delivered_at=NULL,lease_until=NULL''',
        (item['local_id'], at, repeat))
    return True


def enrich(c, items):
    initialize(c)
    rows = {r['local_id']: dict(r) for r in c.execute('SELECT * FROM todo_reminders')}
    for item in items:
        meta = rows.get(item['local_id'], {})
        item.update(remind_at=meta.get('remind_at'), repeat_rule=meta.get('repeat_rule'))
    return items


def cancel(c, identity):
    initialize(c)
    c.execute('''INSERT INTO todo_reminders(local_id,deleted) VALUES(?,1)
        ON CONFLICT(local_id) DO UPDATE SET deleted=1,revision=revision+1,lease_until=NULL''', (identity,))


def manage(c, query, context):
    initialize(c)
    data = json.loads(query)
    op = data.get('operation')
    if op == 'list':
        return {'status': 'completed', 'items': enrich(c, [dict(r) for r in c.execute(
            'SELECT local_id,title,due_date,done FROM todos WHERE done=0 ORDER BY due_date LIMIT 60')])}
    if context.get('agentic_proactive') or context.get('delivery_policy', {}).get('proactive'):
        raise ValueError('user_request_required')
    quote = str(data.get('evidence_quote') or '').strip()
    message_id = context.get('current_event', {}).get('message_id')
    row = c.execute("SELECT content FROM messages WHERE id=? AND role='user'", (message_id,)).fetchone()
    if not row or not quote or quote not in row[0]:
        raise ValueError('current_user_evidence_required')
    if op not in {'create', 'update', 'cancel'}:
        raise ValueError('unsupported reminder operation')
    if op == 'create' and any(word in quote for word in ('不要', '不用', '别提醒', '如果', '假如')):
        raise ValueError('unconditional_arrangement_required')
    identity = str(data.get('local_id') or '')
    existing = c.execute('SELECT * FROM todos WHERE local_id=?', (identity,)).fetchone() if identity else None
    if op != 'create' and not existing:
        return {'status': 'needs_clarification', 'reason': 'choose_existing_item'}
    if op == 'cancel':
        cancel(c, identity)
        c.execute('DELETE FROM todos WHERE local_id=?', (identity,))
        return {'status': 'completed', 'operation': op, 'local_id': identity}
    title = str(data.get('title') or (existing['title'] if existing else '')).strip()
    due = str(data.get('due_date') or (existing['due_date'] if existing else ''))
    if not title or len(title) > 160:
        raise ValueError('invalid reminder title')
    due = local_time(datetime.fromisoformat(due.replace('Z', '+00:00'))).isoformat()
    metadata = c.execute('SELECT * FROM todo_reminders WHERE local_id=?', (identity,)).fetchone() if existing else None
    at = data.get('remind_at') if 'remind_at' in data else (metadata['remind_at'] if metadata else None)
    repeat = None
    if at:
        parsed = local_time(datetime.fromisoformat(at.replace('Z', '+00:00')))
        changed = not metadata or at != metadata['remind_at']
        if changed and parsed <= local_time():
            return {'status': 'needs_clarification', 'reason': 'reminder_time_is_past'}
        if changed and not any(word in quote for word in ('提醒', '叫我', '喊我', '改', '推迟', '提前')):
            raise ValueError('explicit_reminder_required')
    identity = identity if existing else 'chat-reminder:' + str(message_id) + ':' + hashlib.sha256(
        (title + '\n' + due).encode()).hexdigest()[:12]
    item = dict(local_id=identity, title=title, due_date=due, done=False,
                remind_at=at, repeat_rule=repeat)
    if not settings(c, item):
        return {'status': 'needs_clarification', 'reason': 'previous_arrangement_cancelled'}
    c.execute('''INSERT INTO todos(local_id,title,due_date,done,updated_at) VALUES(?,?,?,0,?)
        ON CONFLICT(local_id) DO UPDATE SET title=excluded.title,due_date=excluded.due_date,
        updated_at=excluded.updated_at''', (identity, title, due, local_time().isoformat()))
    return {'status': 'completed', 'operation': op, 'item': item}


def deliver_one(connect, generate, push, now=None):
    now = local_time(now)
    with connect() as c:
        initialize(c)
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('''SELECT t.title,t.done,r.* FROM todo_reminders r JOIN todos t USING(local_id)
            WHERE t.done=0 AND r.deleted=0 AND r.delivered_at IS NULL AND r.remind_at<=?
            AND (r.lease_until IS NULL OR r.lease_until<?) ORDER BY r.remind_at LIMIT 1''',
            (now.isoformat(), now.isoformat())).fetchone()
        if not row:
            c.commit()
            return False
        item = dict(row)
        lease = (now + timedelta(minutes=10)).isoformat()
        c.execute('UPDATE todo_reminders SET lease_until=? WHERE local_id=?', (lease, item['local_id']))
        c.commit()
    fallback = f"你让我提醒的事：{item['title']}。" + ('这条提醒迟到了。' if now - datetime.fromisoformat(item['remind_at']) > timedelta(minutes=5) else '')
    try:
        text = generate(item, fallback) or fallback
    except Exception:
        text = fallback
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        current = c.execute('''SELECT r.*,t.done FROM todo_reminders r JOIN todos t USING(local_id)
            WHERE r.local_id=?''', (item['local_id'],)).fetchone()
        if not current or current['done'] or current['deleted'] or current['revision'] != item['revision'] or current['lease_until'] != lease:
            c.rollback()
            return False
        at = now.isoformat()
        cursor = c.execute("INSERT INTO messages(role,content,created_at,source,message_type) VALUES('assistant',?,?,'scheduled_reminder','text')", (text, at))
        identity = cursor.lastrowid
        c.execute('UPDATE todo_reminders SET delivered_at=?,repeat_rule=NULL,lease_until=NULL WHERE local_id=?', (at, item['local_id']))
        c.commit()
    push([dict(id=identity, role='assistant', content=text, created_at=at, source='scheduled_reminder', message_type='text')])
    return True
