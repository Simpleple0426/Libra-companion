import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from application.turn_pipeline import compact_context, stored_context_json
from infrastructure.models.cli import _parse_codex, codex_session_available


def test_large_prompt_is_replaced_by_metadata():
    value = compact_context({
        'turn_id': 'turn',
        'core_persona': 'x' * 30_000,
        'response_requests': [{'prompt': 'secret' * 10_000, 'model': 'test'}],
    })
    assert value['turn_id'] == 'turn'
    assert value['core_persona']['storage'] == 'omitted_large_field'
    assert value['response_requests'][0]['prompt_chars'] == 60_000
    assert 'prompt' not in value['response_requests'][0]
    assert len(stored_context_json(value)) < 2_000


def test_impossible_codex_usage_is_ignored_but_reply_survives():
    stdout = '\n'.join([
        json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'ok'}}),
        json.dumps({'type': 'turn.completed', 'usage': {
            'input_tokens': 1_050_029_870,
            'cached_input_tokens': 1_000_000_000,
            'output_tokens': 201_306,
            'reasoning_output_tokens': 200_000,
            'total_tokens': 1_050_231_176,
        }}),
    ])
    result = _parse_codex(stdout, 'thread')
    assert result.text == 'ok'
    assert result.usage is None


def test_normal_codex_usage_is_kept():
    stdout = json.dumps({'type': 'turn.completed', 'usage': {
        'input_tokens': 20_000, 'cached_input_tokens': 15_000,
        'output_tokens': 800, 'reasoning_output_tokens': 300,
        'total_tokens': 20_800,
    }})
    assert _parse_codex(stdout, None).usage['total_tokens'] == 20_800


def test_reasoning_tokens_may_exceed_visible_output():
    stdout = json.dumps({'type': 'turn.completed', 'usage': {
        'input_tokens': 20_000, 'cached_input_tokens': 15_000,
        'output_tokens': 800, 'reasoning_output_tokens': 1_200,
        'total_tokens': 20_800,
    }})
    assert _parse_codex(stdout, None).usage['reasoning_output_tokens'] == 1_200


def test_missing_codex_rollout_is_detected(tmp_path, monkeypatch):
    monkeypatch.setenv('LIBRA_CODEX_HOME', str(tmp_path))
    codex_session_available.cache_clear()
    assert not codex_session_available('missing')
    rollout = tmp_path / 'sessions' / '2026' / '10' / '19' / 'rollout-thread-id.jsonl'
    rollout.parent.mkdir(parents=True)
    rollout.write_text('{}', encoding='utf-8')
    codex_session_available.cache_clear()
    assert codex_session_available('thread-id')
