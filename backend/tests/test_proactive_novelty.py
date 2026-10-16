import unittest
from unittest.mock import Mock
from application.proactive_novelty import check


class ProactiveNoveltyTests(unittest.TestCase):
    def test_exact_repeat_rejected_without_model(self):
        model = Mock()
        self.assertFalse(check(['定下来了！'], [{'role': 'assistant', 'content': '定下来了。'}], {}, model))
        model.assert_not_called()

    def test_semantic_restatement_is_rejected(self):
        context = {}
        model = Mock(return_value={'accepted': False, 'reason': '只是复述已定下的名字'})
        self.assertFalse(check(['我刚才又排了一遍，还是觉得libra & simple最适合我们'],
            [{'role': 'user', 'content': '我也要用&'}, {'role': 'assistant', 'content': '定下来：libra & simple'}], context, model))
        self.assertIn('不构成新事件', model.call_args.args[1])
        self.assertFalse(context['proactive_novelty']['accepted'])

    def test_new_progress_can_continue_same_topic(self):
        self.assertTrue(check(['已经到家了'], [{'role': 'assistant', 'content': '我准备回家'}], {},
                              lambda *_: {'accepted': True, 'reason': '真实到达进展'}))

    def test_reviewer_failure_suppresses_message(self):
        self.assertFalse(check(['新的消息'], [{'role': 'assistant', 'content': '旧消息'}], {},
                               Mock(side_effect=RuntimeError('unavailable'))))
