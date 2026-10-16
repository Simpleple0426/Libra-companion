import ast
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

from application.turn_pipeline import PlannedArtifact, policy


def test_sleeping_diary_can_be_saved_and_each_retry_has_its_own_turn():
    tree = ast.parse((Path(__file__).parents[1] / 'app/runtime.py').read_text(encoding='utf8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == '_run_private_memory_prompt')
    contexts = []

    def prepare(*args, **kwargs):
        context = {}
        context['response_plan'] = policy(context, {
            'libra': {'availability': {'value': 'asleep'}}}, {}, proactive=True)
        assert context['delivery_policy']['can_send'] is False
        contexts.append(context)
        return context

    preparation = Mock(side_effect=prepare)
    pipeline = SimpleNamespace(checkpoint=Mock(), instruction=Mock(return_value=''))
    scope = dict(Path=Path, uuid=uuid, _require_awake=Mock(),
                 _prepare_generation_turn=preparation, turn_pipeline=pipeline,
                 codex_lock=threading.Lock(), MEMORY_MODEL='test',
                 run_cli=Mock(return_value=SimpleNamespace(text='{}', session_id=None)),
                 _record_llm_usage=Mock(), _parse_json_object=lambda text: {'diary': '日记'},
                 PlannedArtifact=PlannedArtifact)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'diary-sleeping', 'exec'), scope)
    for _ in range(2):
        result = scope['_run_private_memory_prompt']('写日记', source='diary', allow_sleeping=True)
        assert result.context['delivery_policy']['can_send'] is True
        assert result.context['response_plan']['should_send'] is True
        assert 'suppression_reason' not in result.context['delivery_policy']
    keys = [call.kwargs['source_key'] for call in preparation.call_args_list]
    assert keys[0] != keys[1]
    scope['_run_private_memory_prompt']('写动态', source='moment', allow_sleeping=True)
    assert contexts[-1]['delivery_policy']['can_send'] is False


def test_goodnight_date_uses_shanghai_time():
    from datetime import datetime, timedelta, timezone
    tree = ast.parse((Path(__file__).parents[1] / 'app/runtime.py').read_text(encoding='utf8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == '_diary_period_for_goodnight')
    scope = dict(datetime=datetime, timedelta=timedelta)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'diary-date', 'exec'), scope)
    day, end = scope['_diary_period_for_goodnight'](datetime(2026, 10, 9, 21, tzinfo=timezone.utc))
    assert day == '2026-10-10'
    assert end == datetime(2026, 10, 10, 5)
