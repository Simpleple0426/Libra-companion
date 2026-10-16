import sqlite3
import unittest
from unittest.mock import patch

from application.bedtime_notice import deliver, NOTICE


class BedtimeNoticeTests(unittest.TestCase):
    def test_retry_does_not_repeat_notice(self):
        with sqlite3.connect(':memory:') as db:
            with patch('infrastructure.sqlite.database.save_message', return_value=42) as save:
                self.assertEqual(deliver('2026-09-29', connection=db), 42)
                self.assertEqual(deliver('2026-09-29', connection=db), 42)
                save.assert_called_once_with('assistant', NOTICE, source='bedtime_notice', connection=db)
