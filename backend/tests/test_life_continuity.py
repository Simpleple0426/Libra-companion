import json
import sqlite3
import unittest

from life_prototype.life_continuity import capture, view, record_sent, sent_view


class LifeContinuityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE events(id TEXT PRIMARY KEY,occurred_at TEXT,description TEXT,kind TEXT,activity_id TEXT)')
        self.config = {'books': {'b': {'title': 'Book', 'version': 'v1', 'text': 'x' * 100}}, 'movies': {}}
        self.state = {'active': 'a1', 'activities': {'a1': self.activity('a1', 20)}}

    def activity(self, ident, progress, status='running'):
        return {'id': ident, 'kind': 'reading', 'target': 'b', 'started_at': '2026-10-10T08:00:00+08:00', 'progress': progress, 'status': status}

    def event(self, ident, activity='a1', kind='reading_start', at='2026-10-10T08:00:00+08:00'):
        self.db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (ident, at, 'Observed reading', kind, activity))

    def test_persistent_resource_thread_resumes_across_sessions_and_ends(self):
        self.event('e1')
        capture(self.db, self.state, self.config)
        first = view(self.db, self.state, self.config)['threads'][0]
        self.state['active'] = None
        self.state['activities']['a1']['status'] = 'interrupted'
        self.event('e2', kind='reading_end')
        capture(self.db, self.state, self.config)
        self.assertEqual(view(self.db, self.state, self.config)['threads'][0]['stage'], 'paused')
        self.state['active'] = 'a2'
        self.state['activities']['a2'] = self.activity('a2', 60)
        self.event('e3', activity='a2', at='2026-10-11T08:00:00+08:00')
        capture(self.db, self.state, self.config)
        resumed = view(self.db, self.state, self.config)['threads'][0]
        self.assertEqual(resumed['id'], first['id'])
        self.assertEqual(resumed['progress'], 60)
        self.assertEqual(len(resumed['milestones']), 3)
        self.state['active'] = None
        self.state['activities']['a2'].update(status='completed', progress=100)
        self.event('e4', activity='a2', kind='reading_completed')
        capture(self.db, self.state, self.config)
        capture(self.db, self.state, self.config)
        completed = view(self.db, self.state, self.config)['threads'][0]
        self.assertEqual(completed['stage'], 'completed')
        self.assertEqual(len(completed['milestones']), 4)
        self.assertFalse(completed['is_current_activity'])

    def test_uncommitted_activities_do_not_become_experiences(self):
        capture(self.db, self.state, self.config)
        self.assertEqual(view(self.db, self.state, self.config)['threads'], [])
        self.assertEqual(view(self.db, self.state, self.config)['recent_events'], [])

    def test_read_is_pure_and_live_state_overrides_cached_activity(self):
        self.event('e1')
        capture(self.db, self.state, self.config)
        self.state['active'] = None
        before = self.db.total_changes
        result = view(self.db, self.state, self.config)
        self.assertEqual(result['threads'][0]['stage'], 'paused')
        self.assertEqual(self.db.total_changes, before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)

    def test_latest_progress_without_new_event_is_available(self):
        self.event('e1')
        capture(self.db, self.state, self.config)
        self.state['activities']['a1']['progress'] = 45
        self.assertEqual(view(self.db, self.state, self.config)['threads'][0]['progress'], 45)

    def test_saved_thoughts_are_distinct_from_events_and_rejected_drafts(self):
        self.db.execute('CREATE TABLE life_dynamic_drafts(id TEXT,created_at TEXT,kind TEXT,status TEXT,body TEXT)')
        for ident, status in [('saved', 'pending_display'), ('bad', 'rejected')]:
            self.db.execute('INSERT INTO life_dynamic_drafts VALUES(?,?,?,?,?)', (ident, '2026-10-10', 'leisure_thought', status, json.dumps({'body': 'A private thought', 'activity_id': 'a1'})))
        result = view(self.db, self.state, self.config)
        self.assertEqual([item['id'] for item in result['private_thoughts']], ['saved'])
        self.assertIn('not_event', result['private_thoughts'][0]['semantics'])
        self.assertEqual(result['recent_events'], [])

    def test_delivered_message_log_is_idempotent_bounded_and_ignores_drafts(self):
        record_sent(self.db, [{'content': 'not committed'}, {'id': 1, 'content': 'sticker', 'created_at': '2026-10-10', 'message_type': 'sticker'}])
        self.assertEqual(sent_view(self.db), [])
        messages = [{'id': i, 'content': str(i), 'created_at': '2026-10-10', 'message_type': 'text'} for i in range(50)]
        record_sent(self.db, messages)
        record_sent(self.db, messages[-8:])
        self.assertEqual(len(sent_view(self.db)), 8)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM life_sent_conversation').fetchone()[0], 40)
        self.assertEqual(sent_view(self.db)[-1]['id'], 49)


if __name__ == '__main__':
    unittest.main()
