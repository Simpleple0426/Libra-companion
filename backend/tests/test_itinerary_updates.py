from copy import deepcopy
import unittest

import test_future_appointments as fixture
from life_prototype.clock import utc
from life_prototype.config import canonical
from life_prototype.coarse_plan_updates import enqueue, process_pending, latest, protected
from life_prototype.coarse_plan_execution import requirement
from life_prototype.coarse_plan import DailyAgenda


class ItineraryTests(unittest.TestCase):
    setUp = fixture.FutureAppointmentTests.setUp

    def at_work(self):
        self.clock.advance(10 * 3600)
        self.p.config['household_world']['edges'].append(['home.f1', 'firm.office'])
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['place'] = 'firm.office'
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        self.agenda.ensure()

    def change(self, op='return_home', **fields):
        return dict(operation=op, item_id=None, start_at='2026-09-28T16:00:00+08:00',
                    end_at=None, activity=None, place_id=None, **fields)

    def submit(self, ident, content, changes=(), decision='revise'):
        with self.p.store.connect() as db:
            db.execute('INSERT INTO life_received_messages VALUES(?,?,?)', (ident,
                canonical({'content': content, 'received_at': self.clock.now().isoformat()}), '{}'))
            enqueue(db, ident)
        proposal = {'decision': decision, 'reason': '按用户确认的行程安排', 'evidence_quote': content,
                    'cancel_item_ids': [], 'cancel_appointment_ids': [], 'appointments': [],
                    'itinerary_changes': list(changes)}
        process_pending(self.agenda, proposal=proposal, message_id=ident, expected_revision=self.agenda.read()['revision'])
        return latest(self.agenda)

    def test_early_home_retains_place_and_builds_real_commute(self):
        self.at_work()
        before = self.p.snapshot()
        result = self.submit('home', '今天下午4点出发回家', [self.change()])
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(self.p.snapshot(), before)
        body = self.agenda.read()
        trip = next(i for i in body['items'] if i['kind'] == 'commute' and i.get('coarse_destination') == 'home')
        self.assertEqual(utc(trip['start_at']), utc('2026-09-28T16:00:00+08:00'))
        self.assertGreater(utc(trip['end_at']), utc(trip['start_at']))
        self.assertFalse(any(i.get('activity') == 'user_time' for i in body['items']))
        self.assertFalse(self.p.snapshot().get('companionships'))
        self.clock.advance(2 * 3600)
        self.assertEqual(requirement(self.cog)['reason'], 'coarse_commute_in_progress')
        self.assertEqual(self.p.snapshot()['place'], 'firm.office')
        self.assertTrue(any(protected(i) and i['kind'] == 'meal' for i in body['items']))

    def test_now_home_is_not_a_companion_request(self):
        self.at_work()
        change = self.change(); change['start_at'] = None
        result = self.submit('home', '现在回家吧', [change])
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(requirement(self.cog)['reason'], 'coarse_commute_in_progress')

    def test_urgent_home_normalizes_model_timestamp_to_commit_now(self):
        self.at_work()
        result = self.submit('urgent', '急急急急 回家！', [self.change()])
        self.assertEqual(result['status'], 'applied', result)
        trip = next(i for i in self.agenda.read()['items'] if i['kind'] == 'commute')
        self.assertEqual(utc(trip['start_at']), self.clock.now())

    def test_immediate_evidence_excludes_questions_negations_and_future(self):
        from life_prototype.itinerary_updates import immediate_itinerary
        for text in ['回家了吗', '我回家了', '明天快回家吧', '不要现在回家', '如果现在回家', '他说“回家！”']:
            self.assertFalse(immediate_itinerary(text), text)
        for text in ['回家！', '急急急急 回家！', '快回家吧', '赶紧回家', '现在回家吧']:
            self.assertTrue(immediate_itinerary(text), text)

    def test_delivered_reply_reopens_none_and_applies_only_once(self):
        import sqlite3
        from types import SimpleNamespace
        from application.itinerary_reply_bridge import sync
        self.at_work()
        host = sqlite3.connect(':memory:')
        self.addCleanup(host.close)
        host.execute('CREATE TABLE messages(id INTEGER,role TEXT,content TEXT,source TEXT)')
        engine = SimpleNamespace(store=self.p.store)
        self.assertEqual(sync(engine, host), 0)
        result = self.submit('app:1:ordinary', '几点回家呢 想你了', decision='none')
        self.assertEqual(result['status'], 'none')
        host.execute("INSERT INTO messages VALUES(1,'user','几点回家呢 想你了','chat')")
        host.execute("INSERT INTO messages VALUES(2,'assistant','既然夫人想我，我早点回家。','chat')")
        self.assertEqual(sync(engine, host), 1)
        self.assertEqual(sync(engine, host), 0)
        self.assertEqual(latest(self.agenda)['status'], 'pending')
        proposal = dict(decision='revise',reason='落实自己已发送的承诺', evidence_quote='想你了',
            cancel_item_ids=[],cancel_appointment_ids=[],appointments=[],itinerary_changes=[self.change()])
        process_pending(self.agenda, proposal=proposal)
        self.assertEqual(latest(self.agenda)['status'], 'applied', latest(self.agenda))
        host.execute("INSERT INTO messages VALUES(3,'assistant','我准备回去。','chat')")
        self.assertEqual(sync(engine, host), 0)
        self.assertFalse(self.p.snapshot().get('companionships'))

    def test_reply_bridge_preserves_companion_requests_and_ignores_old_history(self):
        import sqlite3
        from types import SimpleNamespace
        from application.itinerary_reply_bridge import sync
        self.at_work()
        host = sqlite3.connect(':memory:')
        self.addCleanup(host.close)
        host.execute('CREATE TABLE messages(id INTEGER,role TEXT,content TEXT,source TEXT)')
        host.execute("INSERT INTO messages VALUES(1,'assistant','我早点回家。','chat')")
        engine = SimpleNamespace(store=self.p.store)
        self.assertEqual(sync(engine, host), 0)
        self.submit('app:2:ordinary', '陪我去漫展', decision='clarify')
        host.execute("INSERT INTO messages VALUES(2,'user','陪我去漫展','chat')")
        host.execute("INSERT INTO messages VALUES(3,'assistant','我先回家。','chat')")
        self.assertEqual(sync(engine, host), 0)
        self.assertEqual(latest(self.agenda)['status'], 'clarify')

    def test_vague_earlier_time_cannot_be_invented(self):
        self.at_work(); before = self.agenda.read()
        result = self.submit('vague', '今天早点回家吧', [self.change()])
        self.assertNotEqual(result['status'], 'applied')
        self.assertEqual(self.agenda.read(), before)

    def test_clarification_changes_nothing(self):
        self.at_work(); before = self.agenda.read()
        result = self.submit('clarify', '今天早点回家吧', decision='clarify')
        self.assertEqual(result['status'], 'clarify')
        self.assertEqual(self.agenda.read(), before)

    def test_cancel_optional_work_without_entering_companion(self):
        self.at_work()
        target = next(i for i in self.agenda.read()['items'] if i['kind'] == 'work' and utc(i['end_at']) > self.clock.now())
        change = self.change('cancel'); change.update(item_id=target['id'], start_at=None)
        result = self.submit('cancel', '下午别加班了', [change])
        self.assertEqual(result['status'], 'applied', result)
        self.assertFalse(any(i['kind'] == 'work' and utc(i['start_at']) < utc(target['end_at'])
                             for i in self.agenda.read()['items']))

    def test_cannot_cancel_required_meal(self):
        self.at_work(); before = self.agenda.read()
        target = next(i for i in before['items'] if i['kind'] == 'meal' and utc(i['end_at']) > self.clock.now())
        change = self.change('cancel'); change.update(item_id=target['id'], start_at=None)
        result = self.submit('cancel', '晚饭别吃了', [change])
        self.assertNotEqual(result['status'], 'applied')
        self.assertEqual(self.agenda.read(), before)

    def test_replace_with_reading_uses_real_room_and_survives_rebase(self):
        self.at_work()
        change = self.change('replace'); change.update(activity='reading', place_id='home.f2.study',
            end_at='2026-09-28T17:00:00+08:00')
        result = self.submit('read', '下午4点到5点在家看书吧', [change])
        self.assertEqual(result['status'], 'applied', result)
        self.cog.agenda = self.agenda = DailyAgenda(self.cog)
        self.p.config['itinerary_test_rebase'] = True
        body = self.agenda.ensure()
        self.assertFalse(body.get('conflicts'), body.get('conflicts'))
        self.assertTrue(any(i.get('intent') == '阅读' and i['place'] == 'home.f2.study' for i in body['items']))

    def test_unknown_place_is_rejected_atomically(self):
        self.at_work(); before = self.agenda.read()
        change = self.change('replace'); change.update(activity='reading', place_id='unknown',
            end_at='2026-09-28T17:00:00+08:00')
        result = self.submit('read', '下午4点去那里看书到5点', [change])
        self.assertNotEqual(result['status'], 'applied')
        self.assertEqual(self.agenda.read(), before)

    def test_reschedule_preserves_requested_start_end_and_location(self):
        self.at_work()
        target = next(i for i in self.agenda.read()['items'] if i['kind'] == 'work')
        change = self.change('reschedule'); change.update(item_id=target['id'],
            end_at='2026-09-28T17:00:00+08:00')
        result = self.submit('move', '下午工作改到4点到5点', [change])
        self.assertEqual(result['status'], 'applied', result)
        work = [i for i in self.agenda.read()['items'] if i['kind'] == 'work' and i.get('source_message') == 'move']
        self.assertEqual(len(work), 1)
        self.assertEqual(utc(work[0]['start_at']), utc(change['start_at']))
        self.assertEqual(utc(work[0]['end_at']), utc(change['end_at']))
        self.assertEqual(work[0]['place'], target['place'])

    def test_impossible_immediate_destination_clarifies_without_partial_edit(self):
        self.at_work(); before = self.agenda.read()
        change = self.change('replace'); change.update(start_at=None, activity='reading', place_id='home.f2.study',
            end_at='2026-09-28T15:00:00+08:00')
        result = self.submit('read', '现在在家开始看书，到3点结束', [change])
        self.assertEqual(result['status'], 'clarify', result)
        self.assertEqual(self.agenda.read(), before)

    def test_repeated_agent_submission_is_idempotent(self):
        self.at_work()
        result = self.submit('home', '下午4点出发回家', [self.change()])
        self.assertEqual(result['status'], 'applied', result)
        from life_prototype.autonomous_agent import LifeAgent
        from life_prototype.scheduler import Scheduler, DEFAULTS
        agent = LifeAgent(Scheduler(self.chat, DEFAULTS))
        before = self.agenda.read()
        again = agent._tool('retry', 'agenda.revise', {'message_id': 'home',
            'expected_revision': result['detail']['prior_revision'], 'proposal': result['detail']['proposal']})
        self.assertEqual(again['status'], 'applied')
        self.assertEqual(self.agenda.read(), before)

    def test_new_request_can_replace_an_earlier_itinerary_edit(self):
        self.at_work()
        first = self.change('replace'); first.update(activity='reading', place_id='home.f2.study',
            end_at='2026-09-28T17:00:00+08:00')
        self.assertEqual(self.submit('read', '4点到5点看书', [first])['status'], 'applied')
        second = deepcopy(first); second.update(activity='resting', place_id='home.f1.living')
        result = self.submit('rest', '4点到5点改成休息', [second])
        self.assertEqual(result['status'], 'applied', result)
        self.assertFalse(any(i.get('source_message') == 'read' for i in self.agenda.read()['items']))

    def test_plain_chat_leaves_itinerary_unchanged(self):
        self.at_work(); before = self.agenda.read()
        result = self.submit('chat', '今天上班辛苦啦', decision='none')
        self.assertEqual(result['status'], 'none')
        self.assertEqual(self.agenda.read(), before)

    def test_companion_conflict_is_not_overridden(self):
        self.at_work(); before = self.agenda.read()
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['companionships'] = [{'status': 'scheduled', 'start_at': '2026-09-28T17:00:00+08:00', 'end_at': None}]
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        result = self.submit('home', '下午4点回家', [self.change()])
        self.assertNotEqual(result['status'], 'applied')
        self.assertEqual(self.agenda.read(), before)


if __name__ == '__main__': unittest.main()
