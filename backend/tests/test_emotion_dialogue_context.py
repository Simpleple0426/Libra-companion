from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from domains.affect.agent import run


class EmotionDialogueContextTests(unittest.TestCase):
    def test_appraisal_receives_same_dialogue_as_decision(self):
        dialogue = [{'role': 'user', 'content': '我刚才说的是想自己待会儿'}]
        calls = []

        def invoke(kind, text):
            calls.append((kind, text))
            if kind == 'emotion_decision':
                return {'action': 'finish' if len(calls) > 1 else 'appraise', 'reason': 'context'}
            return {}

        payload = {'event': {'event_id': 'event', 'occurred_at': '2026-10-12T00:00:00+00:00'},
                   '_context': {'emotion_recent_messages': dialogue}}
        state = {'instances': [], 'aggregated_emotions': {}, 'needs': {}}
        with patch('domains.affect.agent.appraise', return_value={'goal_appraisals': []}), \
             patch('domains.affect.agent.elicit', return_value=[]), \
             patch('domains.affect.agent.aggregate', return_value={}), \
             patch('domains.affect.agent.prompt', side_effect=lambda kind, data: repr(data)):
            run(payload, state, invoke, datetime.now(timezone.utc), {})
        appraisal_prompt = next(text for kind, text in calls if kind == 'appraisal')
        self.assertIn(repr(dialogue), appraisal_prompt)
