"""Exercise runtime wiring without booting databases or real model processes."""
import ast
from contextvars import ContextVar
import json
from pathlib import Path
import unittest
from unittest.mock import Mock


class RuntimeBridgeTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((Path(__file__).parents[1] / 'app/runtime.py').read_text(encoding='utf-8'))
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name in {'_generate_watch_comment', '_deliver_watch_comment'}]
        self.scope = {'json': json, 'Path': Path, 'codex_lock': Mock(), 'chat_turn_lock': Mock(),
                      '_is_sleeping': Mock(return_value=False), 'active_cognitive_turn': ContextVar('test', default=None)}
        self.scope['codex_lock'].locked.return_value = False
        self.scope['chat_turn_lock'].locked.return_value = False
        exec(compile(ast.Module(body=selected, type_ignores=[]), 'watch-runtime', 'exec'), self.scope)

    def test_calls_existing_main_agent_with_transient_image_and_system_source(self):
        paths = []
        def model(runtime, prompt, **kwargs):
            paths.extend(kwargs['image_paths'])
            self.assertTrue(paths[0].exists())
            self.assertEqual(kwargs['source'], 'movie_watch')
            self.assertNotIn('start_new', kwargs)
            self.assertIn('不是用户发言', prompt)
            return ['评论'], 'existing-main-session', {'watch_summary': '剧情摘要'}
        self.scope['generate_room_reply'] = model
        result = self.scope['_generate_watch_comment']({'title': '电影', 'summary': '',
            'id': 'session', 'last_sequence': 0}, b'frame')
        self.assertEqual(result, (['评论'], '剧情摘要', None))
        self.assertFalse(paths[0].exists())

    def test_chat_has_priority(self):
        self.scope['chat_turn_lock'].locked.return_value = True
        self.scope['generate_room_reply'] = Mock()
        self.assertIsNone(self.scope['_generate_watch_comment']({}, b''))
        self.scope['generate_room_reply'].assert_not_called()

    def test_screenshot_only_silence_preserves_previous_understanding(self):
        def model(runtime, prompt, **kwargs):
            self.assertIn('主动阅读本轮截图', prompt)
            self.assertIn('漏掉的对白', prompt)
            self.assertIn('两人在车站道别', prompt)
            self.assertIn('"played_subtitles": []', prompt)
            self.assertTrue(kwargs['image_paths'][0].exists())
            return [], 'existing-main-session', {'watch_summary': None, 'screenshot_subtitles': ['再见。']}
        self.scope['generate_room_reply'] = model
        result = self.scope['_generate_watch_comment']({'title': '', 'summary': '两人在车站道别',
            'id': 'session', 'last_sequence': 1}, b'frame')
        self.assertEqual(result, ([], '两人在车站道别', ['再见。']))

    def test_delivery_removes_personal_memory_proposal(self):
        class Replies(list):
            payload = {'memory_experience': {'invented': True}}
        replies = Replies(['评论'])
        from contextlib import contextmanager
        db = Mock()
        self.scope['get_connection'] = Mock(return_value=db)
        self.scope['save_room_replies'] = Mock(return_value=[{'content': '评论'}])
        self.scope['_send_push_notification'] = Mock()
        self.scope['_deliver_watch_comment'](replies)
        self.assertNotIn('memory_experience', replies.payload)
        self.scope['save_room_replies'].assert_called_once_with(
            self.scope, replies, 'movie_watch', db)
        db.commit.assert_called_once()
        db.close.assert_called_once()
        self.scope['_send_push_notification'].assert_not_called()
