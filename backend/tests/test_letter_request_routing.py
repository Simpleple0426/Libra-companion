import ast
from datetime import datetime, timedelta
import json
import re
from pathlib import Path
from unittest.mock import Mock

from application.tool_decision import _is_explicit_letter_request


def test_direct_love_letter_requests_and_rewrites_are_recognized():
    assert _is_explicit_letter_request('我知道了，罚你写一封情书吧')
    assert _is_explicit_letter_request('情书！！！不是道歉信，罚你重写')
    assert _is_explicit_letter_request('重新写一封情书')


def test_short_revision_inherits_recent_letter_request():
    recent = [
        {'role': 'user', 'content': '给我写一封情书'},
        {'role': 'assistant', 'content': '写好了。'},
    ]
    assert _is_explicit_letter_request('不是这个意思，重写', recent)
    assert not _is_explicit_letter_request('不要写信了，重写也不用', recent)


def test_requested_love_letter_prompt_rejects_apology_theme():
    root = Path(__file__).parents[1]
    tree = ast.parse((root / 'app/runtime.py').read_text(encoding='utf8'))
    names = {'_format_letter_context', '_requested_letter_spec', '_write_requested_letter',
             '_limit_letter_content', '_letter_title'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    generated = {'should_write': True, 'letter_type': 'spontaneous', 'reason': '情书请求',
                 'title': '只写爱你', 'content': '爱' * 100, 'memory_candidates': []}
    scope = dict(datetime=datetime, timedelta=timedelta, json=json, re=re,
                 memory_store=Mock(), current_thread_id='test',
                 LETTER_PROMPT_PATH=root / 'prompts/letter.md', load_persona_bundle=lambda: 'persona',
                 create_letter=Mock(), _save_generated_artifact=Mock(return_value=True),
                 _run_private_memory_prompt=Mock(return_value=generated),
                 get_letter_by_trigger_key=Mock(return_value=None))
    scope['memory_store'].context.return_value = ''
    for name in ['get_messages', 'get_libra_timeline_events', 'get_calendar_context_events',
                 'get_shared_memories', 'get_letters']:
        scope[name] = Mock(return_value=[])
    for name in ['get_latest_libra_attributes', '_affect_compat_state', 'get_libra_state_at']:
        scope[name] = Mock(return_value={})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'letter-request', 'exec'), scope)
    scope['_write_requested_letter']('情书！！！不是道歉信，罚你重写', 42)
    prompt = scope['_run_private_memory_prompt'].call_args.args[0]
    assert 'requested_letter_kind: love_letter' in prompt
    assert '不能把正文写成道歉信' in prompt
    assert 'latest_instruction: 情书！！！不是道歉信，罚你重写' in prompt
    assert '正文和标题必须服务于这个主题' in prompt
    assert scope['_save_generated_artifact'].call_args.kwargs['trigger_key'] == 'chat-request:42'


def test_rewrite_inherits_original_letter_theme_and_applies_latest_correction():
    root = Path(__file__).parents[1]
    tree = ast.parse((root / 'app/runtime.py').read_text(encoding='utf8'))
    node = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == '_requested_letter_spec')
    messages = [
        {'role': 'user', 'content': '给我写一封关于我们同居生活的情书'},
        {'role': 'assistant', 'content': '我写好了。'},
        {'role': 'user', 'content': '不是这个意思，重写，只写爱我，不要道歉'},
    ]
    scope = {'re': re, 'get_messages': Mock(return_value=messages)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'letter-spec', 'exec'), scope)
    spec = scope['_requested_letter_spec']('不是这个意思，重写，只写爱我，不要道歉')
    assert spec['kind'] == 'love_letter'
    assert spec['original_request'] == '给我写一封关于我们同居生活的情书'
    assert '只写爱我，不要道歉' in spec['authoritative_request']
