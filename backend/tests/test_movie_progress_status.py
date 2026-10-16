import unittest
from unittest.mock import Mock

import test_movie_skill as fixture
from application.local_life import LocalLifeApp, MODE_KEY, ENABLED
from application.life_agent_mailbox import initialize
from life_prototype.cognition import Cognition
from life_prototype.config import canonical
from life_prototype.interaction import Interaction
from life_prototype.scheduler import Scheduler
from life_prototype.skill_movie import heartbeat


class MovieProgressStatusTests(unittest.TestCase):
    setUp = fixture.MovieSkillTests.setUp
    start = fixture.MovieSkillTests.start
    command = fixture.MovieSkillTests.command

    def app(self):
        cog = Cognition(self.p, Mock(kind='fixture', provider='test'), self.cog_config)
        engine = Scheduler(Interaction(cog, self.sleep_config), self.scheduler_config)
        initialize(engine)
        app = LocalLifeApp(lambda key, default='': ENABLED if key == MODE_KEY else default, lambda _: engine)
        app._engine = engine
        app._load = Mock(return_value=engine)
        app._worker_context = object()  # This process owns the live worker.
        return app

    def test_live_status_advances_without_writing_or_double_counting(self):
        self.p.config['movies'][self.key]['duration_seconds'] = 13260
        self.start()
        app = self.app()
        before = self.p.snapshot()
        self.clock.advance(1200)
        active = app.status()['activity']
        self.assertEqual(active['progress'], 1200)
        self.assertEqual(active['total'], 13260)
        self.assertEqual(active['progress_unit'], 'simulated_viewing_seconds')
        self.assertEqual(active['viewing_position']['watched_seconds'], 1200)
        self.assertEqual(self.p.snapshot(), before)
        heartbeat(self.cog)
        self.assertEqual(app.status()['activity']['progress'], 1200)
        self.clock.advance(10)
        self.assertEqual(app.status()['activity']['progress'], 1210)

    def test_unowned_worker_returns_persisted_progress(self):
        self.start()
        app = self.app()
        app._worker_context = None
        self.clock.advance(600)
        self.assertEqual(app.status()['activity']['progress'], 0)

    def test_live_status_stops_at_deadline_and_duration(self):
        self.start()
        app = self.app()
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['activities']['session']['viewing_deadline'] = '2026-09-27T12:00:45+00:00'
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        self.clock.advance(600)
        self.assertEqual(app.status()['activity']['progress'], 45)
        with self.p.store.connect() as db:
            state = self.p.store.read(db)
            state['activities']['session'].pop('viewing_deadline')
            db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        self.assertEqual(app.status()['activity']['progress'], 120)
        self.command('pause', 'interrupt', activity_id='session', reason='结束')
        self.assertIsNone(app.status()['activity'])


if __name__ == '__main__':
    unittest.main()
