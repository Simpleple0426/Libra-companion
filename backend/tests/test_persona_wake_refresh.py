import ast
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock


class PersonaWakeRefreshTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'app/runtime.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_refresh_persona_for_day')
        self.settings = {}
        self.sleep = {'status': 'awake', 'last_wake': {'at': '2026-10-10T07:00:00+08:00'}}
        self.model = MagicMock(return_value=SimpleNamespace(session_id='thread'))
        lock = MagicMock()
        lock.locked.return_value = False
        self.ns = dict(
                       current_thread_id='thread', codex_lock=lock,
                       life_mode=SimpleNamespace(enabled=True, status=lambda **_: {'status': 'ready', 'sleep': self.sleep}),
                       get_app_setting=lambda key, default='': self.settings.get(key, default),
                       set_app_setting=lambda key, value: self.settings.update({key: value}),
                       _is_sleeping=lambda: self.sleep['status'] == 'sleeping',
                       run_cli=self.model, build_reload_prompt=lambda: 'six-file-bundle',
                       _sticker_instruction=lambda: '', CHAT_MODEL='model',
                       _record_llm_usage=MagicMock(), print=lambda *a, **kw: None)
        imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == 'datetime']
        exec(compile(ast.Module(body=imports + [function], type_ignores=[]), 'wake-refresh', 'exec'), self.ns)

    def test_default_now_uses_real_runtime_imports(self):
        self.ns['current_thread_id'] = None
        self.assertFalse(self.ns['_refresh_persona_for_day']())

    def test_refresh_failure_does_not_stop_proactive_loop(self):
        source = Path(__file__).resolve().parents[1] / 'app/runtime.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_checkin_loop')
        self.ns.update(checkin_stop_event=SimpleNamespace(wait=MagicMock(side_effect=[False, True])),
                       _refresh_persona_for_day=MagicMock(side_effect=RuntimeError('refresh failed')),
                       _review_habit_reminders=MagicMock(), _review_local_life_updates=MagicMock(),
                       _review_life_scheduled_checkin=MagicMock())
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'checkin-loop', 'exec'), self.ns)
        self.ns['_checkin_loop']()
        self.ns['_review_local_life_updates'].assert_called_once()
        self.ns['_review_life_scheduled_checkin'].assert_called_once()

    def refresh(self, time):
        return self.ns['_refresh_persona_for_day'](datetime.fromisoformat(time))

    def test_midnight_does_not_refresh_until_next_wake(self):
        self.assertTrue(self.refresh('2026-10-10T08:00:00+08:00'))
        self.assertFalse(self.refresh('2026-10-11T00:30:00+08:00'))
        self.sleep['last_wake']['at'] = '2026-10-11T07:00:00+08:00'
        self.assertTrue(self.refresh('2026-10-11T07:01:00+08:00'))
        self.assertEqual(self.model.call_count, 2)

    def test_no_wake_or_sleeping_does_not_refresh(self):
        self.sleep['last_wake'] = {}
        self.assertFalse(self.refresh('2026-10-10T08:00:00+08:00'))
        self.sleep.update(status='sleeping', last_wake={'at': '2026-10-10T07:00:00+08:00'})
        self.assertFalse(self.refresh('2026-10-10T08:00:00+08:00'))
        self.model.assert_not_called()

    def test_busy_or_failed_refresh_retries_in_same_thread(self):
        self.ns['codex_lock'].locked.return_value = True
        self.assertFalse(self.refresh('2026-10-10T08:00:00+08:00'))
        self.ns['codex_lock'].locked.return_value = False
        self.model.side_effect = RuntimeError('temporarily unavailable')
        self.assertFalse(self.refresh('2026-10-10T08:01:00+08:00'))
        self.assertEqual(self.settings, {})
        self.model.side_effect = None
        self.assertTrue(self.refresh('2026-10-10T08:02:00+08:00'))
        self.assertEqual(self.model.call_args.kwargs['session_id'], 'thread')
