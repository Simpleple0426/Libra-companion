import ast
from datetime import datetime, timedelta
import json
from pathlib import Path
import threading
from unittest.mock import Mock


def scope_for(settings, writer):
    tree = ast.parse((Path(__file__).parents[1] / 'app/runtime.py').read_text(encoding='utf8'))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name in {'_retry_pending_daily_diary', '_diary_retry_loop'}]
    scope = dict(DIARY_ENABLED=True, diary_generation_lock=threading.Lock(),
                 codex_lock=Mock(), datetime=datetime, timedelta=timedelta, json=json,
                 get_app_setting=lambda key, default='': settings.get(key, default),
                 set_app_setting=lambda key, value: settings.update({key: value}),
                 _create_daily_diary=writer)
    scope['codex_lock'].locked.return_value = False
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'diary-retry', 'exec'), scope)
    return scope


def pending():
    return {'daily_diary_pending': json.dumps({'target_date': '2026-10-03',
               'period_end': '2026-10-04T01:00:00', 'reason': 'goodnight_handshake'})}


def test_failure_waits_and_restart_preserves_backoff():
    settings = pending()
    writer = Mock(return_value=False)
    scope = scope_for(settings, writer)
    assert scope['_retry_pending_daily_diary']() is False
    task = json.loads(settings['daily_diary_pending'])
    assert task['attempts'] == 1 and task['retry_at']
    assert scope['_retry_pending_daily_diary']() is False
    restarted = scope_for(settings, writer)
    assert restarted['_retry_pending_daily_diary']() is False
    assert writer.call_count == 1
    task['retry_at'] = '2000-01-01T00:00:00'
    settings['daily_diary_pending'] = json.dumps(task)
    restarted['_retry_pending_daily_diary']()
    assert writer.call_count == 2
    assert writer.call_args.args == ('2026-10-03', datetime(2026, 10, 4, 1))


def test_busy_generation_or_chat_does_not_consume_attempt():
    settings = pending()
    writer = Mock()
    scope = scope_for(settings, writer)
    original = settings.copy()
    scope['codex_lock'].locked.return_value = True
    assert scope['_retry_pending_daily_diary']() is False
    scope['codex_lock'].locked.return_value = False
    scope['diary_generation_lock'].acquire()
    assert scope['_retry_pending_daily_diary']() is False
    scope['diary_generation_lock'].release()
    writer.assert_not_called()
    assert settings == original


def test_success_clears_pending_and_exception_releases_lock():
    settings = pending()
    def save(*args):
        settings['daily_diary_pending'] = ''
        return True
    scope = scope_for(settings, save)
    assert scope['_retry_pending_daily_diary']() is True
    assert scope['_retry_pending_daily_diary']() is False
    settings.update(pending())
    scope['_create_daily_diary'] = Mock(side_effect=RuntimeError('unavailable'))
    try:
        scope['_retry_pending_daily_diary']()
    except RuntimeError:
        pass
    assert not scope['diary_generation_lock'].locked()
    assert json.loads(settings['daily_diary_pending'])['retry_at']


def test_worker_retries_without_life_or_proactive_enabled():
    scope = scope_for({}, Mock())
    scope['checkin_stop_event'] = Mock()
    scope['checkin_stop_event'].wait.side_effect = [False, True]
    scope['_retry_pending_daily_diary'] = Mock()
    scope['_diary_retry_loop']()
    scope['_retry_pending_daily_diary'].assert_called_once()
