"""Verify golden outcomes are reachable in the isolated real storage schema."""
from pathlib import Path
import os
import subprocess
import sys
import unittest


class LifeEvalWorldTests(unittest.TestCase):
    def test_real_itinerary_commits_and_oracle_agree_without_model_calls(self):
        # Fresh interpreter prevents evaluation path overrides leaking into
        # other tests or accidentally binding infrastructure to production data.
        code = r'''
import gc, json, tempfile
from pathlib import Path
from evals.life_world import World, isolate
from evals.life_cases import CASES
from evals.life_grading import grade_turn

class NoModel:
    kind = 'fixture'
    provider = 'oracle-reachability-test'
    def complete(self, *unused):
        raise AssertionError('this test must never call a model')

with tempfile.TemporaryDirectory(prefix='libra-eval-test-') as directory:
    root = Path(directory).resolve()
    isolate(root)
    world = None
    try:
        for case_id, activity, place in [
            ('explicit_read', 'reading', 'home.f2.study'),
            ('explicit_rest', 'resting', 'home.f1.living'),
        ]:
            if world:
                world.close()
            world = World(root / case_id, NoModel())
            case = next(c for c in CASES if c['id'] == case_id)
            turn = case['turns'][0]
            before = world.snapshot()
            world.app.submit_message(case_id, turn['text'])
            world.app._drain_inbox(world.engine)
            message_id = 'app:' + case_id + ':ordinary'
            args = {'message_id': message_id, 'expected_revision': world.cog.agenda.read()['revision'],
                    'proposal': {'decision': 'revise', 'reason': 'golden test proposal',
                    'evidence_quote': turn['text'], 'cancel_item_ids': [], 'cancel_appointment_ids': [],
                    'appointments': [], 'itinerary_changes': [{'operation': 'replace', 'item_id': None,
                    'start_at': '2026-09-28T16:00:00+08:00', 'end_at': '2026-09-28T17:00:00+08:00',
                    'activity': activity, 'place_id': place}]}}
            receipt = world.engine.agent._tool('golden:' + case_id, 'agenda.revise', args)
            assert receipt['status'] == 'applied', receipt
            world.app._publish_events()
            context = world.app.chat_context(message_id=case_id)
            grade = grade_turn(turn['expected'], before, world.snapshot(), context['daily_agenda_review'], context)
            assert grade['passed'], (case_id, grade, world.snapshot()['outbox'])
        assert world.snapshot()['model_calls'] == []
        world.close()
        world = World(root / 'at-work', NoModel(), initial_place='firm.office')
        assert world.p.snapshot()['place'] == 'firm.office'
        assert world.cog.agenda.view()['current_item']['place'] == 'firm.office'
    finally:
        if world:
            world.close()
        gc.collect()
'''
        backend = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-c', code], cwd=backend,
                                env={**os.environ, 'PYTHONUTF8': '1'},
                                capture_output=True, text=True, encoding='utf8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
