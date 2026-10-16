import json
import unittest
from unittest.mock import patch

import test_companionship as companion_fixture
import test_user_time_reservations as reservation_fixture
from life_prototype.cognition import Cognition
from life_prototype.companionship import manual_end, reconcile
from life_prototype.coarse_plan_execution import enter_current


class CompanionshipMemoryTests(unittest.TestCase):
    setUp = companion_fixture.CompanionshipTests.setUp
    send = companion_fixture.CompanionshipTests.send

    def memories(self):
        with self.p.store.connect() as db:
            return {r[0]: {'fact': json.loads(r[1]), 'evidence': json.loads(r[2]),
                           'at': r[3], 'status': r[4]} for r in db.execute(
                "SELECT id,description,evidence,created_at,status FROM life_memories WHERE id LIKE 'mem:companion%'")}

    def test_scheduled_started_and_expired_are_distinct_retrievable_memories(self):
        result = self.send('future', '明天7点陪我看电影，9点结束', title='陪用户看电影',
                           start_at='2026-09-29T07:00:00+08:00', end_at='2026-09-29T09:00:00+08:00')
        ident = result['companion']['id']
        self.clock.advance(27 * 3600)
        reconcile(self.cog)
        self.clock.advance(2 * 3600)
        reconcile(self.cog)
        # Ingest only after the mutable session has ended, then reopen cognition.
        with patch.object(self.cog.calls, 'ask', side_effect=AssertionError('unexpected model call')):
            self.cog.ingest()
        restarted = Cognition(self.p, self.cog.calls.model, self.cog.config)
        restarted.ingest()
        memories = self.memories()
        self.assertEqual(len(memories), 3)
        expected = [('mem:companion-message:future', 'scheduled', '已约定陪用户看电影'),
                    ('mem:' + ident + ':started', 'active', '左然正在陪用户看电影'),
                    ('mem:' + ident + ':expired', 'ended', '陪伴约定已结束，恢复自主生活安排')]
        for key, status, description in expected:
            memory = memories[key]
            self.assertEqual(memory['fact']['description'], description)
            self.assertEqual(memory['fact']['companion']['status'], status)
            self.assertEqual(memory['fact']['companion']['title'], '陪用户看电影')
            self.assertEqual(memory['evidence'], [key.removeprefix('mem:')])
            self.assertEqual(memory['status'], 'observed')
            self.assertIn('不据此推断', memory['fact']['semantics'])
        found = restarted.memory.retrieve('陪用户看电影', 'recall-movie', keyword_only=True)
        self.assertTrue(found)
        self.assertTrue(all('陪用户看电影' in r['keywords'] for r in found))

    def test_changed_title_and_manual_end_keep_event_time_facts(self):
        session = self.send('movie', '现在陪我看电影', title='陪用户看电影')['companion']
        self.clock.advance(60)
        self.send('music', '现在我们听音乐吧', 'update', title='陪用户听音乐')
        self.clock.advance(60)
        manual_end(self.cog, session['id'])
        manual_end(self.cog, session['id'])
        self.cog.ingest()
        self.cog.ingest()
        memories = self.memories()
        self.assertEqual(len(memories), 3)
        self.assertEqual(memories['mem:companion-message:movie']['fact']['companion']['title'], '陪用户看电影')
        ended = memories['mem:' + session['id'] + ':manual-end']['fact']['companion']
        self.assertEqual(ended['title'], '陪用户听音乐')
        self.assertEqual(ended['status'], 'ended')
        self.assertEqual(ended['end_reason'], 'manual')

    def test_explicit_end_retains_the_activity(self):
        self.send('movie', '现在陪我看电影', title='陪用户看电影')
        self.send('end', '不用继续陪我了', 'end')
        self.cog.ingest()
        ended = self.memories()['mem:companion-message:end']['fact']['companion']
        self.assertEqual((ended['status'], ended['title']), ('ended', '陪用户看电影'))

    def test_failed_write_rolls_back_memory_and_cursor_for_retry(self):
        self.send('movie', '现在陪我看电影', title='陪用户看电影')
        self.send('music', '一起听音乐吧', 'update', title='陪用户听音乐')
        from life_prototype.memory_service import add_memory
        with self.p.store.connect() as db:
            before = self.cog._meta(db)['cursor']
        calls = 0

        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('write failed')
            return add_memory(*args)

        with patch('life_prototype.cognition.add_memory', side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, 'write failed'):
                self.cog.ingest()
        self.assertEqual(self.memories(), {})
        with self.p.store.connect() as db:
            self.assertEqual(self.cog._meta(db)['cursor'], before)
        self.cog.ingest()
        self.assertEqual(len(self.memories()), 2)

    def test_unconfirmed_invitation_creates_no_memory(self):
        result = self.send('unknown-time', '陪我看电影', title='陪用户看电影')
        self.assertEqual(result['status'], 'clarify')
        self.cog.ingest()
        self.assertEqual(self.memories(), {})


class ReservationMemoryTests(unittest.TestCase):
    setUp = reservation_fixture.UserTimeTests.setUp
    request = reservation_fixture.UserTimeTests.request
    reserve = reservation_fixture.UserTimeTests.reserve
    start = reservation_fixture.UserTimeTests.start

    def test_reserved_time_is_remembered_only_after_entry_without_fake_outcome(self):
        item = self.reserve()
        self.cog.ingest()
        with self.p.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM life_memories WHERE id LIKE 'mem:coarse-state:%'").fetchone()[0], 0)
        self.assertTrue(self.start(item))
        self.assertFalse(enter_current(self.cog))
        self.cog.ingest()
        self.cog.ingest()
        with self.p.store.connect() as db:
            rows = db.execute("SELECT description,evidence FROM life_memories WHERE id LIKE 'mem:coarse-state:%'").fetchall()
        self.assertEqual(len(rows), 1)
        fact = json.loads(rows[0][0])
        self.assertEqual(fact['reservation']['title'], '陪用户逛漫展')
        self.assertIsNone(fact['reservation']['place'])
        self.assertIn('no user presence or activity outcome inferred', fact['reservation']['semantics'])
        self.assertEqual(json.loads(rows[0][1]), ['coarse-state:' + item['id']])


if __name__ == '__main__':
    unittest.main()
