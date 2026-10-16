from datetime import datetime
from unittest.mock import Mock
import ast
from datetime import timedelta
import hashlib
from pathlib import Path

from application.letter_emotion import understand


def message(text, role='user', at='2026-10-04T10:00:00'):
    return {'role': role, 'content': text, 'created_at': at}


def result(quote, subject='user', source='current'):
    return {'situations': [{'subject': subject, 'description': '用户表达失落',
                           'evidence': [{'source_id': source, 'quote': quote}]}]}


def test_indirect_sadness_uses_context_and_requires_actual_user_quote():
    model = Mock(return_value=result('眼泪一直掉'))
    rows = [message('我等了一整天'), message('后来呢', 'assistant'), message('眼泪一直掉')]
    evidence = understand(rows, datetime(2026, 10, 4, 12), model)
    assert evidence and evidence[0]['evidence'][0]['quote'] == '眼泪一直掉'
    prompt = model.call_args.args[0]
    assert '我等了一整天' in prompt and '转述他人' in prompt and '已结束的过去情绪' in prompt


def test_no_keyword_fallback_for_quote_negation_or_recovered_emotion():
    for text in ['电影里她说很难过', '我并不难过', '昨晚哭了，现在已经好多了']:
        model = Mock(return_value={'situations': []})
        assert understand([message(text)], datetime(2026, 10, 4, 12), model) == []


def test_invalid_quotes_and_other_subjects_cannot_trigger():
    for value in [result('不存在的原话'), result('难过', subject='libra'),
                  result('难过', source='recent:0')]:
        assert understand([message('难过')], datetime(2026, 10, 4, 12), Mock(return_value=value)) == []


def test_stale_emotion_does_not_trigger_model_call():
    model = Mock()
    assert understand([message('很难过', at='2026-10-01T10:00:00')],
                      datetime(2026, 10, 4, 12), model) == []
    model.assert_not_called()


def test_runtime_uses_semantic_evidence_as_letter_candidate():
    tree = ast.parse((Path(__file__).parents[1] / 'app/runtime.py').read_text(encoding='utf8'))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_letter_candidate')
    row = {'id': 1, **message('眼泪一直掉')}
    scope = dict(datetime=datetime, timedelta=timedelta, hashlib=hashlib,
                 get_calendar_context_events=Mock(return_value=[]),
                 get_app_setting=lambda key, default: default,
                 get_messages=Mock(return_value=[row]),
                 get_messages_between=Mock(return_value=[row]),
                 _run_private_memory_prompt=Mock(return_value=result('眼泪一直掉')))
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'letter-candidate', 'exec'), scope)
    candidate = scope['_letter_candidate'](datetime(2026, 10, 4, 12))
    assert candidate['score'] == 4 and candidate['letter_type'] == 'encouragement'
    assert candidate['emotion_evidence'][0]['evidence'][0]['quote'] == '眼泪一直掉'
