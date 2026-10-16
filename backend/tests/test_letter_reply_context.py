import ast
from datetime import datetime, timedelta
import json
import re
from pathlib import Path
import sqlite3
from unittest.mock import Mock, patch

from infrastructure.sqlite import database
from infrastructure.sqlite import content_repository as repository


def test_thread_loads_full_original_and_all_rounds_outside_recent_list(tmp_path):
    path = tmp_path / 'letters.db'
    original = 'Original ' + 'x' * 300 + ' ORIGINAL_END'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE letters(id INTEGER PRIMARY KEY,reply_to_id INTEGER,sender TEXT,content TEXT,created_at TEXT)')
        for values in [(1, None, 'libra', original), (2, 1, 'user', 'first reply'),
                       (3, 1, 'libra', 'legacy reply'), (4, 3, 'user', 'latest reply'),
                       (5, 4, 'libra', 'later reply'), (6, None, 'user', 'unrelated')]:
            db.execute('INSERT INTO letters VALUES(?,?,?,?,?)', (*values, '2026-10-04T12:00:00'))
    def connect():
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        return db
    with patch.object(repository, 'get_connection', connect):
        rows = repository.get_letter_thread(4)
        assert [row['id'] for row in rows] == [1, 2, 3, 4]
        assert rows[0]['content'] == original
        assert repository.get_letter(999) is None


def runtime_scope():
    root = Path(__file__).parents[1]
    tree = ast.parse((root / 'app/runtime.py').read_text(encoding='utf8'))
    names = {'_format_letter_context', '_write_letter_reply', '_limit_letter_content', '_letter_title'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    scope = dict(datetime=datetime, timedelta=timedelta, json=json, re=re,
                 memory_store=Mock(), current_thread_id='test',
                 LETTER_PROMPT_PATH=root / 'prompts/letter.md', load_persona_bundle=lambda: 'persona',
                 create_letter=Mock(), _save_generated_artifact=Mock(return_value=True),
                 _run_private_memory_prompt=Mock(return_value={'content': 'reply body', 'title': 'reply title'}))
    scope['memory_store'].context.return_value = ''
    for name in ['get_messages', 'get_libra_timeline_events', 'get_calendar_context_events',
                 'get_shared_memories', 'get_letters']:
        scope[name] = Mock(return_value=[])
    for name in ['get_latest_libra_attributes', '_affect_compat_state', 'get_libra_state_at']:
        scope[name] = Mock(return_value={})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'letter-runtime', 'exec'), scope)
    return scope


def test_reply_prompt_contains_complete_original_and_sender_and_targets_user_letter():
    scope = runtime_scope()
    original = {'id': 1, 'sender': 'libra', 'content': 'x' * 250 + ' ORIGINAL_END'}
    user = {'id': 2, 'reply_to_id': 1, 'sender': 'user', 'content': 'MY_REPLY'}
    scope['get_letter_thread'] = Mock(return_value=[original, user])
    scope['_write_letter_reply'](user)
    prompt = scope['_run_private_memory_prompt'].call_args.args[0]
    assert original['content'] in prompt and 'MY_REPLY' in prompt
    assert '左然（你写出的信）' in prompt and '用户（她的信）' in prompt
    assert '当前需要回复的用户来信' in prompt
    assert scope['_save_generated_artifact'].call_args.args[5] == 2


def test_replying_to_nonexistent_original_is_rejected_before_saving():
    from fastapi import HTTPException
    from types import SimpleNamespace
    import pytest
    root = Path(__file__).parents[1]
    tree = ast.parse((root / 'app/runtime.py').read_text(encoding='utf8'))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'send_letter')
    node.decorator_list = []
    scope = dict(LetterRequest=object, HTTPException=HTTPException, get_letter=Mock(return_value=None), create_letter=Mock())
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'letter-send', 'exec'), scope)
    with pytest.raises(HTTPException) as error:
        scope['send_letter'](SimpleNamespace(content='reply', reply_to_id=999))
    assert error.value.status_code == 404
    scope['create_letter'].assert_not_called()
