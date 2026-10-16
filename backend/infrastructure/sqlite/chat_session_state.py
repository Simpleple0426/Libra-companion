"""Chat-provider session persistence, independent of memory segmentation.

Keep the legacy configuration keys so existing installations and archives retain
their resume pointer. Remembering a session never rewrites memory provenance.
"""


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
