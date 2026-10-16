"""Synthetic world using real inbox, scheduler, agent, validators and storage."""
import json
import os
from pathlib import Path
import sqlite3


def isolate(root):
    """Call before importing application modules, in a dedicated worker process."""
    root = Path(root).resolve()
    for variable, folder in {
        'LIBRA_RUNTIME_DIR': 'host', 'LIBRA_CONFIG_DIR': 'config',
        'LIBRA_LOG_DIR': 'logs', 'LIBRA_CACHE_DIR': 'cache',
        'LIBRA_BACKUP_DIR': 'backups',
    }.items():
        directory = root / folder
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[variable] = str(directory)
    os.environ['LIBRA_ENV_FILE'] = str(root / 'config' / 'empty.env')
    for name in ('libra.db', 'content.db', 'cognition.db'):
        with sqlite3.connect(root / 'host' / name) as db:
            if name == 'libra.db':
                db.execute('CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,role TEXT,content TEXT,source TEXT)')


class World:
    def __init__(self, root, model, *, reopen=False, initial_place=None):
        from application.local_life import LocalLifeApp, MODE_KEY, RUN_KEY, POLICY_KEY, ENABLED
        from life_prototype.activity_engine import Prototype
        from life_prototype.clock import TestClock
        from life_prototype.cognition import Cognition
        from life_prototype.interaction import Interaction
        from life_prototype.local_configuration import configurations
        from life_prototype.scheduler import Scheduler
        from life_prototype.autonomous_agent import LifeAgent
        from life_prototype.config import canonical
        self.root = Path(root)
        self.clock = TestClock('2026-09-28T14:00:00+08:00')
        world, cognition, sleep, scheduler = configurations()
        self.p = Prototype('synthetic', world, self.clock, root=self.root / 'world')
        if initial_place is not None:
            if initial_place != 'firm.office' or initial_place not in self.p.config['places']:
                raise ValueError('unsupported evaluation initial place')
            # Synthetic connection also used by itinerary domain tests. Keep
            # it identical on reopen; do not change the actor's persisted place.
            edge = ['home.f1', 'firm.office']
            if edge not in self.p.config['household_world']['edges']:
                self.p.config['household_world']['edges'].append(edge)
            if not reopen:
                with self.p.store.connect() as db:
                    state = self.p.store.read(db)
                    state['place'] = initial_place
                    db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        self.cog = Cognition(self.p, model, cognition)
        self.engine = Scheduler(Interaction(self.cog, sleep), scheduler)
        self.engine.agent = LifeAgent(self.engine)
        self.cog.agenda.ensure()
        if not reopen:
            # The actual generator creates the initial workday. Move the actor
            # to its scheduled room so the first tick has no fixture-only move.
            item = self.cog.agenda.view()['current_item']
            with self.p.store.connect() as db:
                state = self.p.store.read(db)
                state['place'] = item['place']
                db.execute("UPDATE life_state SET body=? WHERE name='current'", (canonical(state),))
        settings = {MODE_KEY: ENABLED, RUN_KEY: 'synthetic', POLICY_KEY: json.dumps({
            'initial_state_version': 'eval-v1', 'need_rates_version': 'eval-v1',
            'offline_policy_version': 'eval-v1', 'special_sleep_policy_version': 'eval-v1',
            'source': 'explicit_test_fixture'})}
        self.app = LocalLifeApp(lambda key, default='': settings.get(key, default),
                                lambda _: self.engine, allow_test_fixture=True)
        startup = self.app.startup()
        if startup.get('status') == 'blocked':
            raise RuntimeError('evaluation world startup blocked: ' + str(startup.get('blocker')))

    def close(self):
        self.app.shutdown()

    def snapshot(self):
        from application.life_agent_mailbox import connect
        with self.p.store.connect() as db:
            reviews = [dict(message_id=r[0], status=r[1], detail=json.loads(r[2]) if r[2] else None)
                       for r in db.execute('SELECT message_id,status,receipt FROM life_agenda_messages ORDER BY rowid')]
            steps = [dict(id=r[0], call=json.loads(r[1]), result=json.loads(r[2]) if r[2] else None)
                     for r in db.execute('SELECT id,request,result FROM life_agent_steps ORDER BY rowid')]
            calls = [dict(id=r[0], stage=r[1], status=r[2], metadata=json.loads(r[3]) if r[3] else None)
                     for r in db.execute('SELECT id,stage,status,metadata FROM life_model_calls ORDER BY rowid')]
        with connect(self.engine) as db:
            inbox = [dict(id=r[0], status=r[1], attempts=r[2]) for r in
                     db.execute('SELECT id,status,attempts FROM life_agent_inbox ORDER BY rowid')]
        return {'state': self.p.snapshot(), 'agenda': self.cog.agenda.read(),
                'reviews': reviews, 'steps': steps, 'model_calls': calls, 'inbox': inbox,
                'outbox': self.app.pending_events(100)}
