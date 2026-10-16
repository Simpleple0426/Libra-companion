import ast
from contextvars import ContextVar
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch


class StopAfterInput(RuntimeError):
    pass


class ChatSourceRoutingTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((Path(__file__).parents[1] / 'app/runtime.py').read_text(encoding='utf-8'))
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'_chat_impl', '_chat_turn'}]
        self.scope = {'ChatRequest': object, 'Path': Path, 'datetime': datetime, 'json': json,
            'active_cognitive_turn': ContextVar('test_chat_source', default=None),
            'chat_turn_lock': threading.Lock(), 'get_app_setting': lambda *a: 'false',
            '_sleep_status': lambda: {'sleeping': False}, 'life_mode': SimpleNamespace(enabled=False),
            'turn_pipeline': Mock(), 'pending_chat_image': None}
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'chat-routing', 'exec'), self.scope)
        self.request = SimpleNamespace(request_id=None, message='hello', xhs_attachment=None,
            reply_mode='text', music_context=None, device_context_enabled=False)
        import uuid
        self.scope['uuid'] = uuid

    def test_main_and_music_sources_reach_input_persistence(self):
        self.scope['turn_pipeline'].accept_input.side_effect = StopAfterInput
        with patch('application.tool_decision.ToolDecision', return_value=Mock()):
            for source in ('chat', 'music_room'):
                with self.subTest(source=source), self.assertRaises(StopAfterInput):
                    if source == 'chat':
                        self.scope['_chat_impl'](self.request)
                    else:
                        self.scope['_chat_impl'](self.request, message_source=source)
                self.assertEqual(self.scope['turn_pipeline'].accept_input.call_args.kwargs['source'], source)
                self.assertFalse(self.scope['chat_turn_lock'].locked())
                self.assertIsNone(self.scope['active_cognitive_turn'].get())

    def test_sleeping_input_keeps_its_source(self):
        self.scope['_sleep_status'] = lambda: {'sleeping': True}
        self.scope['current_thread_id'] = 'existing'
        self.scope['turn_pipeline'].accept_input.return_value = 123
        with patch('application.tool_decision.ToolDecision', return_value=Mock()):
            result = self.scope['_chat_impl'](self.request, message_source='music_room')
        self.assertTrue(result['queued_while_sleeping'])
        self.assertEqual(self.scope['turn_pipeline'].accept_input.call_args.kwargs['source'], 'music_room')
