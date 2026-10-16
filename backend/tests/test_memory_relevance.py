import json
import unittest

from domains.memory.relevance import parse_response, select


class MemoryRelevanceTests(unittest.TestCase):
    def test_plain_and_fenced_json_select_same_memory(self):
        response = {'decisions': [{'memory_id': 'm1', 'decision': 'direct', 'reason': '相关历史'}]}
        raw = json.dumps(response, ensure_ascii=False)
        candidates = [{'memory_id': 'm1', 'content': '历史记录'}, {'memory_id': 'm2', 'content': '无关记录'}]
        for text in (raw, '```json\n' + raw + '\n```', '```\n' + raw + '\n```'):
            with self.subTest(text=text):
                selected, decisions = select('问题', [], candidates, lambda _: parse_response(text), '2026-10-10')
                self.assertEqual([m['memory_id'] for m in selected], ['m1'])
                self.assertEqual(decisions[-1]['decision'], 'drop')

    def test_empty_and_malformed_responses_have_specific_codes(self):
        for text, code in ((None, 'empty_memory_relevance_response'),
                           ('  ', 'empty_memory_relevance_response'),
                           ('{"decisions":', 'invalid_memory_relevance_json'),
                           ('[]', 'invalid_memory_relevance'),
                           ('{}', 'invalid_memory_relevance')):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, '^' + code + '$'):
                parse_response(text)

    def test_unknown_and_duplicate_ids_remain_rejected(self):
        item = {'memory_id': 'm1', 'decision': 'direct', 'reason': '相关'}
        for decisions in ([dict(item, memory_id='unknown')], [item, item]):
            with self.subTest(decisions=decisions), self.assertRaisesRegex(ValueError, 'invalid_memory_relevance_id'):
                select('问题', [], [{'memory_id': 'm1'}], lambda _: {'decisions': decisions}, 'now')

    def test_invalid_decision_and_empty_reason_remain_rejected(self):
        for decision, reason in (('keep', '相关'), ('direct', '')):
            with self.subTest(decision=decision), self.assertRaisesRegex(ValueError, 'invalid_memory_relevance_decision'):
                select('问题', [], [{'memory_id': 'm1'}], lambda _: {'decisions': [
                    {'memory_id': 'm1', 'decision': decision, 'reason': reason}]}, 'now')

    def test_all_drop_is_valid(self):
        selected, decisions = select('问题', [], [{'memory_id': 'm1'}],
                                     lambda _: parse_response('{"decisions": []}'), 'now')
        self.assertEqual(selected, [])
        self.assertEqual(decisions[0]['decision'], 'drop')
