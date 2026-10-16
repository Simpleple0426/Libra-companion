from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import Mock, patch

import test_future_appointments as fixture
from life_prototype.clock import utc
from life_prototype.config import canonical
from life_prototype.coarse_plan_schema import pack, unpack
from life_prototype.coarse_plan_updates import validate_proposal
from life_prototype.coarse_plan_execution import requirement, enter_current, validate_wait
from life_prototype.activity_feed import read


class UserTimeTests(unittest.TestCase):
    setUp = fixture.FutureAppointmentTests.setUp
    request = fixture.FutureAppointmentTests.request

    def reserve(self):
        result = self.request('comic-con', [{'title': '陪我逛漫展', 'start_at': '2026-09-29T14:00:00+08:00',
                                            'duration_seconds': 7200}])
        self.assertEqual(result['status'], 'applied', result)
        self.clock.advance(86400)
        body = self.agenda.ensure()
        self.assertFalse(body.get('conflicts'), body.get('conflicts'))
        return next(i for i in body['items'] if i.get('appointment_id'))

    def feed(self):
        with self.p.store.connect() as db:
            return read(db, self.p.store.read(db), self.p.config, limit=None)

    def start(self, item):
        self.clock.advance((utc(item['start_at']) - self.clock.now()).total_seconds())
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['place'] = 'firm.office'
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        return enter_current(self.cog)

    def test_omitted_and_unknown_places_never_require_a_route(self):
        body, state = self.agenda.read(), self.p.snapshot()
        for extra in ({}, {'place_id': '并不存在的漫展场馆'}, {'place_id': 'home.f1.living'}):
            with self.subTest(extra=extra):
                proposal = {'decision': 'revise', 'reason': '预留时间', 'evidence_quote': '明天陪我去漫展',
                            'cancel_item_ids': [], 'cancel_appointment_ids': [],
                            'appointments': [{'title': '陪我逛漫展', 'start_at': '2026-09-29T14:00:00+08:00',
                                              'duration_seconds': 7200, **extra}]}
                with patch('life_prototype.coarse_plan._route', side_effect=AssertionError('must not check a route')):
                    rules = validate_proposal(proposal, {'id': 'request', 'content': '明天陪我去漫展'},
                                              body, state, self.p.config, self.clock.now())
                self.assertIsNone(rules['appointments'][0]['place'])
                self.assertEqual(rules['appointments'][0]['title'], '陪用户逛漫展')

    def test_roundtrip_preserves_specific_title_and_empty_location(self):
        item = self.reserve()
        again = unpack(pack(self.agenda.read()))
        saved = next(i for i in again['items'] if i.get('appointment_id'))
        self.assertEqual(saved['title'], '陪用户逛漫展')
        self.assertEqual(saved['intent'], '陪用户逛漫展')
        self.assertIsNone(saved['place'])
        self.assertEqual(saved['place_name'], '')
        self.assertFalse(any(i.get('destination') is None for i in again['items'] if i['kind'] == 'commute'))
        self.assertEqual(item['appointment_id'], saved['appointment_id'])

    def test_entry_emits_specific_dynamic_without_moving_or_fake_results(self):
        item = self.reserve()
        self.assertFalse(any(i['kind'] == 'user_time_start' for i in self.feed()))
        with patch('life_prototype.home_world.path', side_effect=AssertionError('must not plan a trip')):
            self.assertTrue(self.start(item))
            self.assertEqual(requirement(self.cog)['reason'], 'user_reserved_time')
            self.assertEqual(validate_wait(self.cog)['mode'], 'hold')
        state = self.p.snapshot()
        self.assertEqual(state['place'], 'firm.office')
        self.assertIsNone(state['active'])
        self.assertFalse(self.agenda.view()['pending_transition'])
        events = [i for i in self.feed() if i['kind'] == 'user_time_start']
        self.assertEqual([i['event'] for i in events], ['左然正在陪用户逛漫展'])
        self.assertFalse(any(i['kind'] in {'arrived', 'moving_start'} for i in self.feed()))

    def test_reentry_and_agenda_revision_do_not_duplicate_dynamic(self):
        item = self.reserve()
        self.start(item)
        self.assertFalse(enter_current(self.cog))
        body = deepcopy(self.agenda.read())
        body['revision'] += 1
        for i in body['items']:
            i['id'] += ':revised'
        with self.p.store.connect() as db:
            db.execute('INSERT INTO life_daily_agendas VALUES(?,?,?)', (body['date'], body['revision'], canonical(pack(body))))
        self.assertTrue(enter_current(self.cog))
        self.assertEqual(len([i for i in self.feed() if i['kind'] == 'user_time_start']), 1)

    def test_cancelled_or_elapsed_reservation_has_no_start_dynamic(self):
        item = self.reserve()
        self.clock.advance((utc(item['end_at']) - self.clock.now()).total_seconds())
        enter_current(self.cog)
        self.assertFalse(any(i['kind'] == 'user_time_start' for i in self.feed()))

    def test_chat_context_exposes_user_time_without_claiming_a_location(self):
        from application.local_life import LocalLifeApp, MODE_KEY, ENABLED
        from application.life_agent_mailbox import initialize
        from life_prototype.scheduler import Scheduler
        from life_prototype.local_configuration import configurations
        item = self.reserve()
        self.start(item)
        engine = Scheduler(self.chat, configurations()[3])
        initialize(engine)
        app = LocalLifeApp(lambda key, default='': ENABLED if key == MODE_KEY else default, lambda _: engine)
        app._engine = engine
        app.status = Mock(return_value={'status': 'ready', 'revision': 1, 'place': 'firm.office', 'place_name': '办公室',
                                       'activity': None, 'sleep': {'status': 'awake'},
                                       'user_time': {'title': item['title'], 'location_policy': 'unspecified'}})
        context = app.chat_context()
        self.assertEqual(context['user_time']['title'], '陪用户逛漫展')
        self.assertIsNone(context['place'])
        self.assertIn('user appointment', context['activity_semantics'])


if __name__ == '__main__':
    unittest.main()
