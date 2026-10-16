import ast
from datetime import datetime, timedelta
import json
from pathlib import Path
from unittest.mock import Mock


def scope_for():
    root = Path(__file__).parents[1]
    tree = ast.parse((root / 'app/runtime.py').read_text(encoding='utf8'))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name in {'_review_proactive_letter', '_proactive_letter_loop'}]
    settings = {'proactive_enabled': 'true'}
    scope = dict(datetime=datetime, timedelta=timedelta, json=json,
        get_app_setting=lambda key, default='': settings.get(key, default),
        set_app_setting=lambda key, value: settings.update({key: value}),
        _is_sleeping=Mock(return_value=False), codex_lock=Mock(),
        get_proactive_letter_for_date=Mock(return_value=None),
        get_letter_by_trigger_key=Mock(return_value=None),
        get_messages_between=Mock(return_value=[]),
        _letter_candidate=Mock(return_value={'score': 5, 'letter_type': 'birthday',
                                            'reasons': ['birthday'], 'trigger_key': 'test'}),
        LETTER_PROMPT_PATH=root / 'prompts/letter.md', load_persona_bundle=lambda: 'persona',
        _format_letter_context=Mock(return_value='context'),
        _run_private_memory_prompt=Mock(return_value={'should_write': True, 'content': 'a' * 100}),
        _limit_letter_content=lambda value: value, _letter_title=lambda value, fallback: fallback,
        _save_generated_artifact=Mock(return_value=True), create_letter=Mock())
    scope['codex_lock'].locked.return_value = False
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'proactive-letters', 'exec'), scope)
    return scope, settings


def test_meaningful_event_writes_and_rate_limit_survives_restart():
    scope, settings = scope_for()
    now = datetime(2026, 10, 4, 10)
    scope['_review_proactive_letter'](now)
    scope['_save_generated_artifact'].assert_called_once()
    assert scope['_save_generated_artifact'].call_args.kwargs['generation_source'] == 'proactive'
    scope['_review_proactive_letter'](now + timedelta(hours=1))
    assert scope['_run_private_memory_prompt'].call_count == 1
    assert settings['letter_last_review_at'] == now.isoformat()


def test_disabled_sleeping_busy_and_existing_letter_skip_generation():
    for blocked in ['disabled', 'sleeping', 'busy', 'already_sent', 'night']:
        scope, settings = scope_for()
        now = datetime(2026, 10, 4, 10)
        if blocked == 'disabled': settings['proactive_enabled'] = 'false'
        if blocked == 'sleeping': scope['_is_sleeping'].return_value = True
        if blocked == 'busy': scope['codex_lock'].locked.return_value = True
        if blocked == 'already_sent': scope['get_proactive_letter_for_date'].return_value = {'id': 1}
        if blocked == 'night': now = now.replace(hour=23)
        scope['_review_proactive_letter'](now)
        scope['_run_private_memory_prompt'].assert_not_called()


def test_low_score_duplicate_trigger_and_model_decline_do_not_send():
    for reason in ['low_score', 'duplicate', 'decline']:
        scope, _ = scope_for()
        if reason == 'low_score': scope['_letter_candidate'].return_value['score'] = 2
        if reason == 'duplicate': scope['get_letter_by_trigger_key'].return_value = {'id': 1}
        if reason == 'decline': scope['_run_private_memory_prompt'].return_value = {'should_write': False}
        scope['_review_proactive_letter'](datetime(2026, 10, 4, 10))
        scope['_save_generated_artifact'].assert_not_called()


def test_worker_keeps_running_after_review_exception():
    scope, _ = scope_for()
    scope['checkin_stop_event'] = Mock()
    scope['checkin_stop_event'].wait.side_effect = [False, False, True]
    scope['_review_proactive_letter'] = Mock(side_effect=[RuntimeError('unavailable'), None])
    scope['_proactive_letter_loop']()
    assert scope['_review_proactive_letter'].call_count == 2


def test_new_user_message_can_trigger_review_before_six_hours():
    scope, settings = scope_for()
    now = datetime(2026, 10, 4, 10)
    settings.update(letter_last_review_at=(now - timedelta(minutes=11)).isoformat(),
                    letter_last_review_user_id='1')
    scope['get_messages_between'].return_value = [{'id': 2, 'role': 'user'}]
    scope['_review_proactive_letter'](now)
    scope['_save_generated_artifact'].assert_called_once()
    assert settings['letter_last_review_user_id'] == '2'
