"""Durable accounting for enabled local-App CLI calls; no validation-budget reset."""
import json
from pathlib import Path
import threading

from .config import canonical
from .model_client import ModelError


class OperationalLedger:
    """Minimal CliModel budget protocol for continuous local operation.

    P4 bounds retries per durable job.  This ledger counts every CLI process and
    permanently stops new calls after a provider-level block such as HTTP 402.
    It is operational accounting, not one of the closed experiment budgets.
    """

    def __init__(self, directory, *, call_timeout_seconds=150):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "operations.json"
        self.call_timeout_seconds = call_timeout_seconds
        self._lock = threading.Lock()
        if not self.path.exists():
            self._save({"schema": 1, "unit": "cli_model_call", "attempts": 0,
                        "wall_seconds": 0.0, "charged_calls": [], "blocked": None})

    def _read(self):
        return json.loads(self.path.read_text(encoding="utf8"))

    def _save(self, value):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(canonical(value), encoding="utf8")
        temporary.replace(self.path)

    def remaining(self):
        return self.call_timeout_seconds

    def reserve(self, stage):
        with self._lock:
            value = self._read()
            if value.get("blocked"):
                raise ModelError("local life CLI calls are blocked pending operator review")
            value["attempts"] += 1
            value["last_stage"] = stage
            self._save(value)

    def charge_call(self, call_id, seconds):
        with self._lock:
            value = self._read()
            if call_id in value["charged_calls"]:
                return
            value["charged_calls"].append(call_id)
            value["wall_seconds"] += max(0.0, float(seconds))
            self._save(value)

    def block(self, reason):
        with self._lock:
            value = self._read()
            # Ordinary transport/turn failures use the scheduler's bounded
            # retries. They must not permanently disable every future call.
            value["last_failure"] = str(reason)
            if str(reason) != "CLI turn failed":
                value["blocked"] = str(reason)
            self._save(value)

    def resume_after_review(self, expected_reason, reason):
        """Explicit operator recovery; preserve all usage and prior evidence."""
        from datetime import datetime, timezone
        if not reason.strip():
            raise ValueError("operator review reason required")
        with self._lock:
            value = self._read()
            if value.get('blocked') != expected_reason:
                raise ValueError('block changed since review')
            value.setdefault('reviews', []).append({
                'at': datetime.now(timezone.utc).isoformat(),
                'previous_block': expected_reason, 'reason': reason})
            value['blocked'] = None
            self._save(value)


class SerializedModel:
    """Serialize calls on the owning agent's lane without sharing session history."""

    def __init__(self, model, lock, model_wait=None):
        self.model, self.lock = model, lock
        self.kind = model.kind
        self.provider = model.provider
        from contextlib import nullcontext
        self.model_wait = model_wait or nullcontext

    def complete(self, stage, payload):
        with self.model_wait():
            with self.lock:
                return self.model.complete(stage, payload)

    def cancel(self):
        return self.model.cancel()
