"""Validated tool calls with uniform outcomes, deadlines and private-data-free logs.

Reads have bounded waiting, not forced thread cancellation. Writes stay on the
caller thread to preserve transactions; late completion is recorded honestly.
"""
from concurrent.futures import Future
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import inspect
import logging
import math
import subprocess
import threading
import time
import uuid

from application.tool_contracts import OPERATIONS, RETRIEVAL_OPERATIONS, TOOL_SPECS

_deadline = ContextVar('tool_deadline', default=None)
_slots = threading.BoundedSemaphore(16)


def remaining_timeout(default):
    """Bound adapter network/subprocess waits by the current tool deadline."""
    deadline = _deadline.get()
    remaining = default if deadline is None else min(default, deadline - time.monotonic())
    if remaining <= 0:
        raise TimeoutError('tool_deadline_exceeded')
    return remaining


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    tool: str
    status: str
    data: object
    error: dict | None
    duration_ms: float
    timeout_seconds: float
    deadline_exceeded: bool = False
    _cause: Exception | None = field(default=None, repr=False, compare=False)

    @property
    def ok(self):
        return self.status == 'completed'

    def to_dict(self):
        return {name: getattr(self, name) for name in (
            'call_id', 'tool', 'status', 'data', 'error', 'duration_ms',
            'timeout_seconds', 'deadline_exceeded')} | {'ok': self.ok}

    def unwrap(self):
        """Explicit domain boundary; preserve existing domain-specific catches."""
        if not self.ok:
            raise self._cause or RuntimeError(self.error['code'])
        return self.data


class ToolBusy(RuntimeError):
    pass


def _is_timeout(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
            return True
        error = error.__cause__
    return False


def _read(handler, args, kwargs, timeout):
    slots = _slots
    if not slots.acquire(blocking=False):
        raise ToolBusy('tool_capacity_exhausted')
    future = Future()
    context = copy_context()

    def run():
        try:
            def invoke():
                remaining_timeout(timeout)
                return handler(*args, **kwargs)
            future.set_result(context.run(invoke))
        except BaseException as error:
            future.set_exception(error)
        finally:
            slots.release()

    try:
        threading.Thread(target=run, daemon=True, name='tool-read').start()
    except BaseException:
        slots.release()
        raise
    return future.result(timeout=timeout)


class ToolExecutor:
    def __init__(self, services, *, source, sink=None, timeouts=None):
        self.services, self.source, self.sink = services, source, sink
        self.timeouts = dict(timeouts or {})
        for name, value in self.timeouts.items():
            if (name not in TOOL_SPECS or isinstance(value, bool)
                    or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
                raise ValueError('invalid_tool_timeout')
        self.receipts = []

    def bind_retriever(self, retriever):
        self.services.update({
            'search_personal_memory': lambda *a, **kw: retriever.personal_memory(*a, **kw),
            'search_shared_history': lambda *a, **kw: retriever.shared_history_store.context_for(*a, **kw),
            'read_shared_history': lambda *a, **kw: retriever.shared_history_store.read_excerpt(*a, **kw),
            'search_character': lambda *a, **kw: retriever.character_store.search(*a, **kw),
        })

    def call(self, name, *args, **kwargs):
        started = time.monotonic()
        spec = TOOL_SPECS.get(name) if isinstance(name, str) else None
        timeout = self.timeouts.get(name, spec.timeout_seconds) if spec else 0
        receipt = dict(call_id=uuid.uuid4().hex, tool=name if isinstance(name, str) else '<invalid>',
                       source=self.source, created_at=datetime.now(timezone.utc).isoformat())
        status, data, error, cause = 'failed', None, None, None
        code = 'unsupported_tool'
        token = None
        deadline = started + timeout
        parent = _deadline.get()
        if parent is not None:
            deadline = min(deadline, parent)
        invoked = False
        try:
            if spec is None:
                raise ValueError('unsupported_tool')
            code = 'invalid_arguments'
            spec.bind(args, kwargs)
            code = 'adapter_unavailable'
            handler = self.services.get(spec.adapter)
            if not callable(handler):
                raise ValueError('tool_adapter_unavailable:' + name)
            code = 'invalid_arguments'
            inspect.signature(handler).bind(*args, **kwargs)
            token = _deadline.set(deadline)
            wait = remaining_timeout(timeout)
            code = 'execution_failed'
            invoked = True
            data = handler(*args, **kwargs) if spec.write or spec.inline else _read(handler, args, kwargs, wait)
            code = 'invalid_result'
            if not isinstance(data, spec.result_types):
                raise TypeError('invalid_tool_result')
            if name == 'weather.current' and (len(data) != 2 or not isinstance(data[0], dict)
                                              or not isinstance(data[1], (dict, type(None)))):
                raise TypeError('invalid_tool_result')
            status = 'completed'
        except Exception as caught:
            cause = caught
            if _is_timeout(caught):
                status, code = 'timeout', 'timeout'
            elif isinstance(caught, ToolBusy):
                status, code = 'busy', 'capacity_exhausted'
            error = {'code': code, 'type': type(caught).__name__,
                     'outcome_unknown': bool(spec and spec.write and invoked)}
            data = None
        finally:
            if token is not None:
                _deadline.reset(token)
        elapsed = time.monotonic() - started
        exceeded = bool(spec and time.monotonic() > deadline)
        result = ToolResult(receipt['call_id'], receipt['tool'], status, data, error,
                            round(elapsed * 1000, 2), timeout, exceeded, cause)
        receipt.update(status=status, duration_ms=result.duration_ms, timeout_seconds=timeout,
                       deadline_exceeded=exceeded, write=bool(spec and spec.write))
        if error:
            receipt.update(error=error['type'], error_code=error['code'],
                           outcome_unknown=error['outcome_unknown'])
        self.receipts.append(receipt)
        print('[tool_execution] ' + json.dumps(receipt, ensure_ascii=False), flush=True)
        if self.sink:
            try:
                self.sink(dict(receipt))
            except Exception:
                logging.getLogger(__name__).warning('Tool receipt sink failed')
        return result
