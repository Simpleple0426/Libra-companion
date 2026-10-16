import unittest
from unittest.mock import Mock

import test_companionship as fixture
from application.local_life import LocalLifeApp, MODE_KEY, ENABLED
from application.life_agent_mailbox import initialize
from life_prototype.scheduler import Scheduler
from life_prototype.local_configuration import configurations


class CompanionAppTests(unittest.TestCase):
    setUp = fixture.CompanionshipTests.setUp
    send = fixture.CompanionshipTests.send
    def test_status_context_and_manual_end(self):
        session = self.send('start', '现在陪我逛漫展吧', title='陪用户逛漫展')['companion']
        engine = Scheduler(self.chat, configurations()[3])
        initialize(engine)
        app = LocalLifeApp(lambda key, default='': ENABLED if key == MODE_KEY else default, lambda _: engine)
        app._engine = engine
        app._load = Mock(return_value=engine)
        app._ensure_worker = Mock(return_value=engine)
        status = app.status()
        self.assertEqual(status['companion']['id'], session['id'])
        self.assertEqual(status['coarse_activity']['title'], '陪用户逛漫展')
        context = app.chat_context()
        self.assertIsNone(context['place'])
        self.assertEqual(context['companion']['id'], session['id'])
        app.end_companion(session['id'])
        app.end_companion(session['id'])
        self.assertIsNone(app.status()['companion'])

    def test_agent_loop_commits_companion_then_waits(self):
        from life_prototype.autonomous_agent import LifeAgent
        from life_prototype.config import canonical
        from life_prototype.coarse_plan_updates import enqueue
        engine = Scheduler(self.chat, configurations()[3])
        agent = LifeAgent(engine)
        with self.p.store.connect() as db:
            db.execute('INSERT INTO life_received_messages VALUES(?,?,?)', ('invitation',
                canonical({'content': '现在陪我逛漫展吧', 'received_at': self.clock.now().isoformat()}), '{}'))
            enqueue(db, 'invitation')

        def choose(*unused):
            if agent.pending_message():
                return {'tool': 'companion.revise', 'arguments_json': canonical({
                    'message_id': 'invitation', 'expected_revision': self.p.snapshot()['revision'],
                    'action': 'start', 'session_id': None, 'title': '陪用户逛漫展',
                    'start_at': None, 'end_at': None, 'outdoor': None, 'evidence_quote': '现在陪我逛漫展吧'})}
            return {'tool': 'wait', 'arguments_json': canonical({'seconds': 60, 'reason': '陪伴中，等待用户报备'})}

        self.cog.calls.ask = Mock(side_effect=choose)
        result = agent.run('test-companion')
        self.assertEqual(result['agent_status'], 'waiting')
        self.assertEqual(result['coarse_execution']['reason'], 'companion_active')
        self.assertIsNone(agent.pending_message())

    def test_explicit_chat_end_publishes_ended_state_and_delivery(self):
        self.send('start', '现在陪我逛漫展吧')
        engine = Scheduler(self.chat, configurations()[3])
        initialize(engine)
        app = LocalLifeApp(lambda key, default='': ENABLED if key == MODE_KEY else default, lambda _: engine)
        app._engine = engine
        app._load = Mock(return_value=engine)
        app._ensure_worker = Mock(return_value=engine)
        app.refresh_chat_context()
        self.assertIsNotNone(app.query_context()['companion'])
        result = app.submit_message('explicit-end', '结束陪伴')
        self.assertEqual(result['status'], 'delivered')
        self.assertEqual(result['receipt']['status'], 'ended')
        self.assertIsNone(app.query_context().get('companion'))
        self.assertIsNone(app.status()['companion'])


if __name__ == '__main__':
    unittest.main()
