"""Narrow explicit local-write capabilities. No model-supplied SQL or permissions."""


def resolve(text, now=None):
    from application.tool_decision import resolve_local_actions
    return resolve_local_actions(text, now)


def execute(connection, action, key, now):
    """Called only with the program resolver's actions in the receipt transaction."""
    kind, title, day = action['type'], action['title'], action['date']
    if kind == 'create_todo':
        rows = connection.execute('SELECT local_id FROM todos WHERE title=? AND substr(due_date,1,10)=?', (title, day)).fetchall()
        if rows:
            return {'status': 'already_exists', 'type': kind, 'title': title}
        connection.execute('INSERT INTO todos(local_id,title,due_date,done,updated_at) VALUES (?,?,?,0,?)', (key, title, day + 'T00:00:00', now))
    elif kind == 'create_habit':
        rows = connection.execute('SELECT local_id FROM habits WHERE title=? AND active_from<=? AND (active_until IS NULL OR active_until>=?)', (title, day, day)).fetchall()
        if rows:
            return {'status': 'already_exists', 'type': kind, 'title': title}
        connection.execute('INSERT INTO habits(local_id,title,active_from,updated_at) VALUES (?,?,?,?)', (key, title, day, now))
    else:
        table = 'todos' if kind == 'complete_todo' else 'habits'
        if kind not in {'complete_todo', 'complete_habit'}:
            raise ValueError('unsupported_capability')
        rows = connection.execute('SELECT * FROM ' + table + ' WHERE title=?', (title,)).fetchall()
        if len(rows) != 1:
            return {'status': 'needs_clarification', 'type': kind, 'title': title}
        row = rows[0]
        from domains.affect.service import capture_completion
        if kind == 'complete_todo':
            if row['done']:
                return {'status': 'already_completed', 'type': kind, 'title': title}
            connection.execute('UPDATE todos SET done=1,completed_at=?,updated_at=? WHERE id=?', (now, now, row['id']))
        else:
            if row['active_from'] > day or row['active_until'] and row['active_until'] < day:
                return {'status': 'needs_clarification', 'type': kind, 'title': title}
            changed = connection.execute('INSERT OR IGNORE INTO habit_checkins(habit_local_id,checked_date) VALUES (?,?)', (row['local_id'], day)).rowcount
            if not changed:
                return {'status': 'already_completed', 'type': kind, 'title': title}
            capture_completion(connection, 'habit_reminder', row['local_id'] + ':' + day, title, now)
    return {'status': 'completed', 'type': kind, 'title': title, 'date': day}
