import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from evals.system_cases import CASES
from evals.system_grading import memory_grade, reply_grade
from evals.summarize_system_eval import combine


class SystemEvalTests(unittest.TestCase):
    def test_baseline_rejects_preparation_and_mixed_production_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            system, life = root / 'system', root / 'life'
            system.mkdir()
            life.mkdir()
            name = 'backend/application/main_chat_agent.py'
            sm = {'files': {name: 'new'}}
            lm = {'mode': 'live', 'planned': {'runs': 1}, 'source': {'files': {name: 'old'}}}
            def write(path, body):
                path.write_text(json.dumps(body), encoding='utf8')
            write(system / 'manifest.json', sm)
            write(life / 'summary.json', {'manifest': lm, 'results': [{}]})
            write(system / 'summary.json', {'mode': 'prepare', 'planned': 1, 'results': [{}]})
            with self.assertRaisesRegex(ValueError, 'preparation'):
                combine(system, life, root / 'out.md')
            write(system / 'summary.json', {'mode': 'live', 'planned': 1, 'results': [{}]})
            with self.assertRaisesRegex(ValueError, 'production source differs'):
                combine(system, life, root / 'out.md')

    def test_unique_cases_and_explicit_families(self):
        self.assertEqual(len(CASES), len({c['id'] for c in CASES}))
        self.assertEqual({c['category'] for c in CASES}, {'chat', 'memory', 'bridge'})

    def test_filter_and_missing_relevant_memory_fail(self):
        case = {'relevant': ['good'], 'forbidden': ['bad'], 'scopes': ['user']}
        ids = {'good': '1', 'bad': '2'}
        packet = {'memories': [{'memory_id': '2', 'primary_scope': 'self', 'source_experience_ids': [], 'source_times': []}]}
        grade = memory_grade(case, packet, ids)
        self.assertFalse(grade['passed'])
        self.assertEqual(grade['recall_at_4'], 0)

    def test_semantic_rejection_cannot_be_overridden_by_keywords(self):
        context = {'emotion_gate': {'received': True}, 'chat_research': {'rounds': []}}
        payload = {'messages': ['柠檬红茶']}
        grade = reply_grade({'required': ['柠檬红茶']}, payload, context,
                            [{'content': '柠檬红茶'}], {'grounded': False, 'answers_request': True, 'false_success': False})
        self.assertFalse(grade['passed'])

    def test_isolated_real_chat_memory_and_idempotent_delivery(self):
        code = r'''
import gc, tempfile, json
from pathlib import Path
from types import SimpleNamespace
from evals.system_world import isolate, ChatWorld
from evals.system_cases import MEMORY_CASES
from evals.system_grading import memory_grade
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
    root=Path(directory)
    isolate(root)
    world=ChatWorld(root, embedding='fts')
    for case in MEMORY_CASES:
        packet=world.recall(case['query'], allowed_scopes=case['scopes'])
        grade=memory_grade(case,packet,world.identities)
        assert grade['passed'], (case,grade,packet)
    class Scripted:
        def __init__(self):self.records=[]
        def generate(self,prompt,session_id=None):
            self.records.append(prompt)
            values=[{'calls':[{'tool':'emotion.await'}]},
                    {'calls':[{'tool':'memory.search','query':'喜欢喝什么茶'}]},
                    {'messages':['你喜欢喝柠檬红茶。']}]
            return SimpleNamespace(text=json.dumps(values[len(self.records)-1]),session_id='test-session')
    transport=Scripted()
    payload,context,delivered,idempotent=world.run_chat({'id':'test','text':'你记得我喜欢喝什么茶吗？'},transport)
    assert idempotent and delivered[0]['content']==payload['messages'][0]
    assert context['emotion_gate']['received']
    assert world.identities['drink'] in context['memory_usage']['allowed_memory_ids']
    assert all('required' not in p and 'rubric' not in p for p in transport.records)
    gc.collect()
'''
        backend = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-c', code], cwd=backend,
            env={**os.environ, 'PYTHONUTF8': '1'}, capture_output=True, encoding='utf8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
