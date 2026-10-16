import unittest
from unittest.mock import Mock, MagicMock, patch
from application.local_life import LocalLifeApp, MODE_KEY, ENABLED
from domains.world.current_context import project

from application.local_life import _chat_activity_view, _chat_fine_agenda_view, _recent_state_entries


class ChatLifeContextTests(unittest.TestCase):
    def test_activity_view_keeps_human_readable_current_details(self):
        activity = {
            "id": "activity:reading:1",
            "kind": "reading",
            "status": "running",
            "started_at": "2026-09-29T20:00:00+08:00",
            "target": "book-internal-id",
            "target_name": "局外人",
            "description": "左然正在书房阅读《局外人》",
            "progress": 1200,
            "total": 45000,
            "private_engine_field": "must-not-leak",
        }

        projected = _chat_activity_view(activity)

        self.assertEqual(projected["target_name"], "局外人")
        self.assertEqual(projected["description"], "左然正在书房阅读《局外人》")
        self.assertEqual(projected["started_at"], "2026-09-29T20:00:00+08:00")
        self.assertNotIn("private_engine_field", projected)

    def test_chat_reads_detached_snapshot_without_querying_life(self):
        app = LocalLifeApp(lambda key, default='': ENABLED if key == MODE_KEY else default, Mock())
        app._chat_snapshot = ({'activity': {'kind': 'reading'},
            'current_message_effect': {'message_id': 'app:old:ordinary'}}, {}, {})
        app.chat_context = Mock(side_effect=AssertionError('live query'))
        context = app.query_context(message_id='new')
        self.assertNotIn('current_message_effect', context)
        self.assertIsNone(context['daily_agenda_review'])
        context['activity']['kind'] = 'changed'
        self.assertEqual(app.query_context()['activity']['kind'], 'reading')
        app.chat_context.assert_not_called()

    def test_response_context_includes_concrete_life_state(self):
        life = {'activity': {'kind': 'reading', 'target_name': 'Book', 'progress': 1200},
                'sleep': 'awake', 'revision': 42}
        self.assertEqual(project({'local_life': life}, 'response')['local_life'], life)

    def test_life_publish_refreshes_snapshot_and_failure_clears_it(self):
        app = LocalLifeApp(lambda key, default='': ENABLED if key == MODE_KEY else default, Mock())
        app._engine = MagicMock()
        app.chat_context = Mock(return_value={'revision': 1})
        with patch('application.local_life.mailbox_connect') as connect:
            connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = []
            app._engine.store.connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = []
            app.refresh_chat_context()
            self.assertEqual(app.query_context()['revision'], 1)
            app.chat_context.return_value = {'revision': 2, 'activity': None}
            app.refresh_chat_context()
            self.assertEqual(app.query_context()['revision'], 2)
            app.chat_context.side_effect = RuntimeError('unavailable')
            app.refresh_chat_context()
            self.assertIsNone(app.query_context())

    def test_empty_activity_is_explicitly_absent(self):
        self.assertIsNone(_chat_activity_view(None))

    def test_chat_context_bounds_completed_session_history(self):
        entries = {
            'old-1': {'status': 'completed'},
            'old-2': {'closed_at': '2026-10-01T00:00:00Z'},
            'old-3': {'ended_at': '2026-10-02T00:00:00Z'},
            'active': {'status': 'running'},
        }
        projected = _recent_state_entries(entries, 1)
        self.assertEqual(set(projected), {'old-3', 'active'})

    def test_chat_fine_agenda_omits_historical_plan_bodies(self):
        projected = _chat_fine_agenda_view({
            'current_item': {'id': 'current'},
            'plans': [{'large_private_plan': 'x' * 10000}],
            'semantics': 'future_intentions',
        })
        self.assertEqual(projected['current_item']['id'], 'current')
        self.assertNotIn('plans', projected)

    def test_recent_sent_material_updates_without_live_life_query(self):
        app = LocalLifeApp(lambda key, default='': ENABLED if key == MODE_KEY else default, Mock())
        engine = Mock()
        app._engine = engine
        app._chat_snapshot = ({'life_continuity': {'recent_sent_messages': []}}, {}, {})
        app._sent_conversation_context = (engine, [{'id': 1, 'content': 'Already shared'}])
        app.chat_context = Mock(side_effect=AssertionError('live query'))
        context = app.query_context()
        self.assertEqual(context['life_continuity']['recent_sent_messages'][0]['id'], 1)
        context['life_continuity']['recent_sent_messages'].clear()
        self.assertEqual(len(app.query_context()['life_continuity']['recent_sent_messages']), 1)
        app._engine = Mock()
        self.assertEqual(app.query_context()['life_continuity']['recent_sent_messages'], [])


if __name__ == "__main__":
    unittest.main()
