from datetime import datetime
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from infrastructure.sqlite.chat_session_state import ChatSessionState, weekly_session_key


class WeeklyChatRotationTests(unittest.TestCase):
    def setUp(self):
        self.connections = []
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.db"
        with self.connect() as connection:
            connection.execute("CREATE TABLE memory_config(key TEXT PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO memory_config VALUES('main_thread_id','old-thread')")
        self.state = ChatSessionState(self.connect)

    def tearDown(self):
        for connection in self.connections:
            connection.close()
        self.temp.cleanup()

    def connect(self, write=False):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        self.connections.append(connection)
        return connection

    def test_existing_installation_adopts_current_week(self):
        self.assertFalse(self.state.weekly_rotation_due("2026-10-19"))
        self.assertEqual(self.state.current(), "old-thread")

    def test_new_week_remains_due_until_new_thread_is_saved(self):
        self.state.weekly_rotation_due("2026-10-12")
        self.assertTrue(self.state.weekly_rotation_due("2026-10-19"))
        self.state.request_fresh("old-thread", "handoff")
        self.assertIsNone(self.state.current())
        self.assertTrue(self.state.weekly_rotation_due("2026-10-19"))
        self.state.remember("new-thread")
        self.state.mark_week("2026-10-19")
        self.assertFalse(self.state.weekly_rotation_due("2026-10-19"))
        self.assertEqual(self.state.current(), "new-thread")

    def test_invalid_session_is_not_restored_after_restart(self):
        self.state.invalidate('old-thread', 'missing_codex_rollout')
        self.assertIsNone(self.state.restore_shared('fallback-thread'))
        self.state.remember('replacement-thread')
        self.assertEqual(self.state.restore_shared(), 'replacement-thread')


class WeekBoundaryTests(unittest.TestCase):
    def test_monday_before_four_belongs_to_previous_week(self):
        before = datetime.fromisoformat("2026-10-19T03:59:00+08:00")
        after = datetime.fromisoformat("2026-10-19T04:00:00+08:00")
        self.assertEqual(weekly_session_key(before), "2026-10-12")
        self.assertEqual(weekly_session_key(after), "2026-10-19")


if __name__ == "__main__":
    unittest.main()
