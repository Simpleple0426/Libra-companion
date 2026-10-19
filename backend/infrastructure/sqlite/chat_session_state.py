"""Chat-provider session persistence, independent of memory segmentation.

Keep the legacy configuration keys so existing installations and archives retain
their resume pointer. Remembering a session never rewrites memory provenance.
"""

from datetime import datetime, timedelta, timezone


def weekly_session_key(now=None):
    """Return the Monday date for the 04:00 Asia/Shanghai life week."""
    local_timezone = timezone(timedelta(hours=8))
    moment = now or datetime.now(local_timezone)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=local_timezone)
    life_day = (moment.astimezone(local_timezone) - timedelta(hours=4)).date()
    return (life_day - timedelta(days=life_day.weekday())).isoformat()


def current_session(connection):
    row = connection.execute(
        "SELECT value FROM memory_config WHERE key='main_thread_id'"
    ).fetchone()
    return row[0] if row else None


class ChatSessionState:
    def __init__(self, connect):
        self.connect = connect

    def current(self):
        with self.connect() as connection:
            return current_session(connection)

    def restore_shared(self, fallback=None):
        """Recover the shared pointer, including an unfinished legacy rotation."""
        with self.connect(True) as connection:
            session_id = current_session(connection)
            if not session_id:
                previous = connection.execute(
                    "SELECT value FROM memory_config WHERE key='previous_main_thread_id' "
                    "AND EXISTS (SELECT 1 FROM memory_config "
                    "WHERE key='start_fresh_thread' AND value='1')"
                ).fetchone()
                session_id = (previous[0] if previous else None) or fallback
            if session_id:
                connection.execute(
                    "INSERT INTO memory_config VALUES ('main_thread_id',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (session_id,)
                )
            connection.execute("DELETE FROM memory_config WHERE key='start_fresh_thread'")
            return session_id

    def fresh_requested(self):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM memory_config WHERE key='start_fresh_thread'"
            ).fetchone()
            return bool(row and row[0] == '1')

    def remember(self, session_id):
        if not session_id:
            return
        with self.connect(True) as connection:
            connection.execute(
                "INSERT INTO memory_config VALUES ('main_thread_id',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (session_id,)
            )
            connection.execute("DELETE FROM memory_config WHERE key='start_fresh_thread'")

    def weekly_rotation_due(self, week_key):
        """Return whether the shared session belongs to an earlier Libra week.

        Existing installations adopt the current week on first use.  This
        avoids rotating merely because the feature was deployed mid-week.
        """
        with self.connect(True) as connection:
            row = connection.execute(
                "SELECT value FROM memory_config WHERE key='main_thread_week'"
            ).fetchone()
            if row:
                return row[0] != week_key
            connection.execute(
                "INSERT INTO memory_config VALUES ('main_thread_week',?)",
                (week_key,),
            )
            return False

    def mark_week(self, week_key):
        with self.connect(True) as connection:
            connection.execute(
                "INSERT INTO memory_config VALUES ('main_thread_week',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (week_key,),
            )

    def request_fresh(self, previous, handoff):
        with self.connect(True) as connection:
            for key, value in (('previous_main_thread_id', previous),
                               ('daily_thread_handoff', handoff),
                               ('start_fresh_thread', '1')):
                connection.execute(
                    "INSERT INTO memory_config VALUES (?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
                )
            connection.execute("DELETE FROM memory_config WHERE key='main_thread_id'")
