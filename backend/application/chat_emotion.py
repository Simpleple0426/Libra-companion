"""Turn-local emotion work; only the chat thread merges its completed snapshot."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy
from datetime import datetime, timezone
import time
from application.tool_execution import remaining_timeout


_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='chat-emotion')


class ChatEmotion:
    def __init__(self, context, process, initial_state, apply, timeout=300):
        self.context, self.apply, self.timeout = context, apply, timeout
        self.initial_state = deepcopy(initial_state)
        self.result = None
        isolated = deepcopy(context)
        context['emotion_gate'] = {'status': 'processing', 'received': False,
                                   'started_at': datetime.now(timezone.utc).isoformat()}

        def work():
            started = time.perf_counter()
            state = process(isolated)
            return isolated, state, round((time.perf_counter() - started) * 1000, 2)

        self.future = _workers.submit(copy_context().run, work)

    def wait(self):
        if self.result is not None:
            return self.result
        started = time.perf_counter()
        gate = self.context['emotion_gate']
        state = self.initial_state
        try:
            isolated, updated, duration = self.future.result(timeout=remaining_timeout(self.timeout))
            if isinstance(updated, dict):
                state = updated
            self.context['appraisal'] = isolated.get('appraisal', {})
            if 'emotion_agent' in isolated:
                self.context['emotion_agent'] = isolated['emotion_agent']
            event_id = isolated.get('current_event', {}).get('unified_event_id')
            if event_id:
                self.context['current_event']['unified_event_id'] = event_id
            degraded = isolated.get('degraded_components', [])
            self.context['degraded_components'] = list(dict.fromkeys(
                self.context.get('degraded_components', []) + degraded))
            gate.update(status='unavailable' if 'affect_pending_or_unavailable' in degraded else 'completed',
                        processing_ms=duration)
        except Exception as error:
            gate.update(status='failed', error=type(error).__name__)
            self.context.setdefault('degraded_components', []).append('emotion_or_need_update_unavailable')
        self.apply(state)
        gate.update(received=True, wait_ms=round((time.perf_counter() - started) * 1000, 2),
                    received_at=datetime.now(timezone.utc).isoformat())
        self.result = {'status': gate['status'], 'state_revision': state.get('revision'),
                       'assessment': self.context.get('emotion_agent', {}),
                       'emotions': state.get('aggregated_emotions', {}), 'mood': state.get('mood', {}),
                       'needs': state.get('needs', {}),
                       'tone_guidance': self.context.get('response_plan', {}).get('tone_guidance', ''),
                       'note': '内部情绪参考，具体回应由你决定，不要向用户汇报参数。'
                               if gate['status'] == 'completed' else '本轮情绪处理未完成，以下仅为已有状态，不要臆测新的情绪变化。'}
        return self.result
