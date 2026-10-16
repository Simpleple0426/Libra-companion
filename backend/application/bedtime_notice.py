"""Durable, once-per-night chat notice before automatic sleep."""

NOTICE = '夜深了，我先去休息了。你也记得照顾好自己，晚安。'


def deliver(night, *, connection=None):
    from infrastructure.sqlite.database import get_connection, save_message
    owns_connection = connection is None
    db = get_connection() if owns_connection else connection
    try:
        db.execute('CREATE TABLE IF NOT EXISTS bedtime_notices '
                   '(night TEXT PRIMARY KEY, message_id INTEGER NOT NULL)')
        if owns_connection:
            db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT message_id FROM bedtime_notices WHERE night=?', (night,)).fetchone()
        if old:
            return old[0]
        message_id = save_message('assistant', NOTICE, source='bedtime_notice', connection=db)
        db.execute('INSERT INTO bedtime_notices VALUES (?,?)', (night, message_id))
        if owns_connection:
            db.commit()
        return message_id
    except Exception:
        if owns_connection:
            db.rollback()
        raise
    finally:
        if owns_connection:
            db.close()
