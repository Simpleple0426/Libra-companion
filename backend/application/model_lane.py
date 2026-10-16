"""Serialized model lane with foreground-turn priority and content-free timings."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import threading
import time

_turn = ContextVar('foreground_model_turn', default=None)


@contextmanager
def measure(name):
    started = time.monotonic()
    try:
        yield
    finally:
        turn = _turn.get()
        if turn is not None:
            with turn['lock']:
                turn['timings'][name] = turn['timings'].get(name, 0) + time.monotonic()-started


def timed(name):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with measure(name):
                return fn(*args, **kwargs)
        return wrapped
    return decorate


class ModelLane:
    def __init__(self):
        self._condition = threading.Condition()
        self._busy = False
        self._foreground = 0
        self._local = threading.local()

    @property
    def foreground_pending(self):
        with self._condition:
            return self._foreground > 0

    def locked(self):
        with self._condition:
            return self._busy or self._foreground > 0

    @contextmanager
    def foreground(self):
        # copy_context propagates the same turn to chat's helper threads.
        turn = {'lock':threading.Lock(), 'timings':{}, 'active':True}
        token = _turn.set(turn)
        with self._condition:
            self._foreground += 1
        try:
            yield turn['timings']
        finally:
            with self._condition:
                turn['active'] = False
                self._foreground -= 1
                self._condition.notify_all()
            _turn.reset(token)

    def __enter__(self):
        with measure('model_lane_wait_seconds'):
            with self._condition:
                while self._busy or (self._foreground and not (_turn.get() or {}).get('active')):
                    self._condition.wait()
                self._busy = True
        self._local.started = time.monotonic()
        return self

    def __exit__(self, *exc):
        turn = _turn.get()
        if turn is not None:
            with turn['lock']:
                name = 'model_lane_hold_seconds'
                turn['timings'][name] = turn['timings'].get(name,0) + time.monotonic()-self._local.started
        with self._condition:
            self._busy = False
            self._condition.notify_all()
