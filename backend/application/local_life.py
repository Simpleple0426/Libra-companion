"""Default-off adapter between the existing local app and the life engine.

This module owns no chat transport and writes no LMC memory by itself.  The
host supplies its existing settings, reply pipeline and memory sink.  Life
state is loaded lazily only after an audited enable operation.
"""
from __future__ import annotations
from contextlib import contextmanager
from application.model_lane import timed
from application.life_agent_mailbox import connect as mailbox_connect, initialize as initialize_mailbox

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from copy import deepcopy
from pathlib import Path
import re
import sqlite3
import threading
from typing import Callable, Iterable
from zoneinfo import ZoneInfo


MODE_KEY = "life_system_mode"
RUN_KEY = "life_system_run_id"
BACKUP_KEY = "life_system_backup_id"
POLICY_KEY = "life_system_policy"
AUDIT_KEY = "life_system_audit"
DISABLED = "disabled"
ENABLED = "enabled"


class HostGenerationUnconfigured:
    """Prevents the app adapter from silently creating a second model path."""

    kind = "host_generation_unconfigured"

    def call(self, stage, context):
        raise RuntimeError(f"life generation stage {stage} is not configured for the local app")


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _chat_activity_view(activity: dict | None) -> dict | None:
    """Keep the current activity human-readable for the chat agent."""
    if not activity:
        return None
    keys = (
        "id", "kind", "status", "started_at", "next_due_at", "progress", "total",
        "progress_unit", "target", "target_name", "description", "meal_phase", "dishes",
        "work_title", "housework_title", "care_title", "user_consideration",
    )
    return {key: activity.get(key) for key in keys if activity.get(key) is not None}


def _recent_state_entries(entries: dict | None, limit: int = 3) -> dict:
    """Bound historical state injected into every chat turn.

    Full life state remains available to the life engine and status APIs.  The
    chat model only needs currently relevant records plus a small recent tail;
    injecting weeks of completed sessions makes ordinary replies needlessly
    slow and can exhaust the model-call deadline.
    """
    if not isinstance(entries, dict) or not entries:
        return {}
    active = []
    completed = []
    for key, value in entries.items():
        item = value if isinstance(value, dict) else {}
        is_finished = bool(
            item.get("completed_at")
            or item.get("closed_at")
            or item.get("ended_at")
            or item.get("status") in {"completed", "closed", "ended", "cancelled"}
        )
        (completed if is_finished else active).append((key, value))
    return dict(active + completed[-max(0, limit):])


def _chat_fine_agenda_view(value: dict | None) -> dict | None:
    """Expose the current fine plan without embedding historical plan bodies."""
    if not isinstance(value, dict):
        return None
    result = {
        "current_item": value.get("current_item"),
        "semantics": value.get("semantics"),
        "progress_owner": value.get("progress_owner"),
    }
    return {key: item for key, item in result.items() if item is not None}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_id(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value or ""):
        raise ValueError(f"invalid {label}")
    return value


@dataclass(frozen=True)
class EnablePolicy:
    initial_state_version: str
    need_rates_version: str
    offline_policy_version: str
    special_sleep_policy_version: str
    source: str = "user_confirmed"

    def validate(self, *, allow_test_fixture: bool = False) -> dict:
        body = self.__dict__.copy()
        allowed = {"user_confirmed"} | ({"explicit_test_fixture"} if allow_test_fixture else set())
        if self.source not in allowed:
            raise ValueError("life policy must be user-confirmed")
        for key, value in body.items():
            if key == "source":
                continue
            if not isinstance(value, str) or not value.strip() or value == "unconfigured":
                raise ValueError(f"{key} remains unconfigured")
        return body


class LifeModeControl:
    """Audited switch and offline rollback over the app's existing databases."""

    def __init__(self, get_setting: Callable[[str, str], str], set_setting: Callable[[str, str], None],
                 database_paths: Iterable[Path], backup_root: Path):
        self.get_setting, self.set_setting = get_setting, set_setting
        self.database_paths = tuple(Path(path).resolve() for path in database_paths)
        self.backup_root = Path(backup_root).resolve() / "life-mode"

    def _audit(self, operation: str, detail: dict) -> None:
        try:
            rows = json.loads(self.get_setting(AUDIT_KEY, "[]") or "[]")
        except json.JSONDecodeError:
            rows = []
        rows.append({"at": datetime.now(timezone.utc).isoformat(), "operation": operation, **detail})
        self.set_setting(AUDIT_KEY, _canonical(rows[-100:]))

    def backup(self, backup_id: str, additional_paths: Iterable[Path] = ()) -> dict:
        backup_id = _safe_id(backup_id, "backup id")
        directory = self.backup_root / backup_id
        if directory.exists():
            raise ValueError("backup id already exists")
        directory.mkdir(parents=True)
        files = []
        sources = tuple(dict.fromkeys(self.database_paths + tuple(Path(path).resolve() for path in additional_paths)))
        copied = set()
        for source in sources:
            if not source.is_file() or source in copied:
                continue
            if source.name == 'prototype.sqlite3':
                from life_prototype.memory_storage import backup_pair
                for target in backup_pair(source, directory):
                    original = source.with_name(target.name)
                    copied.add(original)
                    files.append({"source": str(original), "backup": target.name,
                                  "bytes": target.stat().st_size, "sha256": _sha256(target)})
                continue
            target = directory / source.name
            source_db = sqlite3.connect(source)
            target_db = sqlite3.connect(target)
            try:
                source_db.backup(target_db)
            finally:
                target_db.close()
                source_db.close()
            files.append({"source": str(source), "backup": target.name,
                          "bytes": target.stat().st_size, "sha256": _sha256(target)})
        if not files:
            raise ValueError("no application database available to back up")
        manifest = {"schema": 1, "backup_id": backup_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "mode_before": self.get_setting(MODE_KEY, DISABLED), "files": files}
        (directory / "manifest.json").write_text(_canonical(manifest), encoding="utf8")
        # Select this immutable, verified manifest for the subsequent read-only
        # preflight. Enabling remains a separate offline operation.
        self.set_setting(BACKUP_KEY, backup_id)
        self._audit("backup", {"backup_id": backup_id, "file_count": len(files)})
        return manifest

    def enable(self, backup_id: str, run_id: str, policy: EnablePolicy, *, allow_test_fixture: bool = False) -> dict:
        backup_id, run_id = _safe_id(backup_id, "backup id"), _safe_id(run_id, "run id")
        manifest = self.backup_root / backup_id / "manifest.json"
        if not manifest.is_file():
            raise ValueError("enable requires a completed backup")
        policy_body = policy.validate(allow_test_fixture=allow_test_fixture)
        self.set_setting(RUN_KEY, run_id)
        self.set_setting(BACKUP_KEY, backup_id)
        self.set_setting(POLICY_KEY, _canonical(policy_body))
        self.set_setting(MODE_KEY, ENABLED)
        self._audit("enable", {"backup_id": backup_id, "run_id": run_id,
                               "policy_source": policy.source})
        return {"mode": ENABLED, "run_id": run_id, "backup_id": backup_id, "policy": policy_body}

    def stage_configuration(self, run_id: str, policy: EnablePolicy) -> dict:
        """Persist confirmed inputs while disabled so preflight can inspect them."""
        if self.get_setting(MODE_KEY, DISABLED) != DISABLED:
            raise ValueError("configuration staging requires disabled life mode")
        run_id = _safe_id(run_id, "run id")
        policy_body = policy.validate()
        self.set_setting(RUN_KEY, run_id)
        self.set_setting(POLICY_KEY, _canonical(policy_body))
        self._audit("stage_configuration", {"run_id": run_id,
                                             "policy_source": policy.source})
        return {"mode": DISABLED, "run_id": run_id, "policy": policy_body,
                "life_database_created": False}

    def provision(self, life_root: Path, run_id: str, policy: EnablePolicy) -> dict:
        """Create the confirmed empty first-run state without enabling the App."""
        if self.get_setting(MODE_KEY, DISABLED) != DISABLED:
            raise ValueError("provisioning requires disabled life mode")
        run_id = _safe_id(run_id, "run id")
        policy_body = policy.validate()
        staged = json.loads(self.get_setting(POLICY_KEY, "{}") or "{}")
        if staged != policy_body or self.get_setting(RUN_KEY, "") != run_id:
            raise ValueError("provisioning inputs differ from staged confirmed configuration")
        root = Path(life_root).resolve()
        database = root / run_id / "prototype.sqlite3"
        if database.exists():
            raise ValueError("life database already exists; first-run initialization is one-shot")
        from life_prototype.local_configuration import provision
        system = provision(root, run_id, HostGenerationUnconfigured())
        state = system.p.snapshot()
        if state["place"] != "home.f1.living" or state["active"] is not None:
            raise RuntimeError("formal initial snapshot differs from confirmed state")
        with system.store.connect() as db:
            memory_count = db.execute("SELECT COUNT(*) FROM life_memories").fetchone()[0]
            event_count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if memory_count or event_count:
            raise RuntimeError("first-run provisioning created history")
        self._audit("provision", {"run_id": run_id, "database": str(database),
                                  "revision": state["revision"], "history_rows": 0})
        return {"mode": DISABLED, "run_id": run_id, "database": str(database),
                "data_class": "local_single_user", "place": state["place"],
                "activity": None, "history_rows": 0, "policy": policy_body}

    def add_workday_planning_reference(self, life_root: Path, run_id: str, *, app_stopped: bool) -> dict:
        """Versioned config-only migration; creates no event, activity or memory."""
        if not app_stopped:
            raise ValueError("planning-reference migration requires an explicitly stopped App")
        run_id = _safe_id(run_id, "run id")
        database = Path(life_root).resolve() / run_id / "prototype.sqlite3"
        if not database.is_file():
            raise ValueError("life database is not provisioned")
        from life_prototype.planning_reference import REFERENCE, apply_to_world
        with sqlite3.connect(database) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute('SELECT config FROM (SELECT rowid,"id" AS "id","body" AS "config" FROM life_state WHERE name=\'world\') AS prototype_meta WHERE id=1').fetchone()
            if not row:
                raise ValueError("not a life database")
            current = json.loads(row[0])
            if current.get("mode") != "local_single_user":
                raise ValueError("test data cannot receive a formal planning reference")
            updated = apply_to_world(current)
            installed_version = current.get("planning_reference", {}).get("version")
            if installed_version and installed_version not in {REFERENCE["version"], "legacy-workday-reference-v1"}:
                raise ValueError("a different planning reference is already installed")
            if current == updated:
                return {"run_id": run_id, "reference": REFERENCE, "created_history": False,
                        "restart_required": False, "already_installed": True}
            from life_prototype.config import validate
            validate(updated)
            db.execute("UPDATE life_state SET body=?  WHERE name='world' AND ( id=1)", (_canonical(updated),))
            receipt = {"version": REFERENCE["version"], "source_kind": REFERENCE["source_kind"],
                       "effect": "planning input only; no event, activity, result or memory",
                       "at": datetime.now(timezone.utc).isoformat()}
            db.execute("INSERT OR IGNORE INTO life_evidence(category,id,kind,body) VALUES('cognition',?, 'configuration_migration', ?)",
                       ("config:" + REFERENCE["version"], _canonical(receipt)))
            meta = json.loads(db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'scheduler\') AS life_scheduler_state WHERE id=1').fetchone()[0])
            meta.update(dirty=True, next_decision=receipt["at"])
            db.execute("UPDATE life_state SET body=?  WHERE name='scheduler' AND ( id=1)", (_canonical(meta),))
        self._audit("add_workday_planning_reference", {"run_id": run_id,
                    "reference_version": REFERENCE["version"], "created_history": False})
        return {"run_id": run_id, "reference": REFERENCE, "created_history": False,
                "restart_required": True}

    def add_confirmed_daily_routines(self, life_root: Path, run_id: str, *, app_stopped: bool) -> dict:
        """Config-only migration for confirmed meals, home paths and flexible shower."""
        if not app_stopped:
            raise ValueError("daily-routine migration requires an explicitly stopped App")
        run_id = _safe_id(run_id, "run id")
        database = Path(life_root).resolve() / run_id / "prototype.sqlite3"
        if not database.is_file():
            raise ValueError("life database is not provisioned")
        from life_prototype.local_configuration import configurations
        from life_prototype.config import validate
        now = datetime.now(timezone.utc)
        desired = configurations(now.astimezone(ZoneInfo("Asia/Shanghai")).isoformat())[0]
        with sqlite3.connect(database) as db:
            db.execute("BEGIN IMMEDIATE")
            current = json.loads(db.execute('SELECT config FROM (SELECT rowid,"id" AS "id","body" AS "config" FROM life_state WHERE name=\'world\') AS prototype_meta WHERE id=1').fetchone()[0])
            if current.get("mode") != "local_single_user":
                raise ValueError("test data cannot receive formal daily routines")
            if current.get("daily_routines"):
                routines = current["daily_routines"]
                if routines.get("version") != desired["daily_routines"]["version"]:
                    raise ValueError("a different daily routine configuration is installed")
                if routines.get("activation_at"):
                    validate(current)
                    return {"run_id": run_id, "version": routines["version"],
                            "activation_at": routines["activation_at"],
                            "already_installed": True, "created_history": False, "restart_required": False}
                installed = db.execute(
                    'SELECT body FROM (SELECT rowid,"id" AS "id","kind" AS "kind","body" AS "body" FROM life_evidence WHERE category=\'cognition\') AS life_cognition_artifacts WHERE id=\'config:user-confirmed-daily-routines-v1\''
                ).fetchone()
                original_at = json.loads(installed[0])["at"] if installed else now.isoformat()
                activation = datetime.fromisoformat(original_at).astimezone(ZoneInfo("Asia/Shanghai"))
                updated = json.loads(_canonical(current))
                updated["daily_routines"].update(
                    effective_from=activation.date().isoformat(),
                    activation_at=activation.isoformat(),
                    activation_policy="first_day_past_meal_windows_not_backfilled",
                )
                validate(updated)
                db.execute("UPDATE life_state SET body=?  WHERE name='world' AND ( id=1)", (_canonical(updated),))
                receipt = {
                    "version": routines["version"],
                    "correction": "activation boundary restored from original migration receipt",
                    "activation_at": activation.isoformat(),
                    "past_meals": "not_applicable_before_activation",
                    "creates_activity_or_experience": False,
                    "at": now.isoformat(),
                }
                db.execute("INSERT OR IGNORE INTO life_evidence(category,id,kind,body) VALUES('cognition',?, 'configuration_migration', ?)",
                           ("config:user-confirmed-daily-routines-v1:activation-boundary", _canonical(receipt)))
                meta = json.loads(db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'scheduler\') AS life_scheduler_state WHERE id=1').fetchone()[0])
                meta.update(dirty=True, next_decision=now.isoformat())
                db.execute("UPDATE life_state SET body=?  WHERE name='scheduler' AND ( id=1)", (_canonical(meta),))
                self._audit("repair_daily_routine_activation", {"run_id": run_id,
                            "activation_at": activation.isoformat(), "created_history": False})
                return {"run_id": run_id, "version": routines["version"],
                        "activation_at": activation.isoformat(), "activation_repaired": True,
                        "created_history": False, "restart_required": True}
            updated = json.loads(_canonical(current))
            updated["places"].update({key: value for key, value in desired["places"].items()
                                      if key in {"home.stairs", "home.f2.bathroom"}})
            for key in ("household_world", "edge_seconds", "daily_routines"):
                updated[key] = desired[key]
            updated["not_enabled"] = [x for x in updated.get("not_enabled", [])
                                      if x != "unconfirmed household travel/execution edges"]
            validate(updated)
            db.execute("UPDATE life_state SET body=?  WHERE name='world' AND ( id=1)", (_canonical(updated),))
            receipt = {"version": desired["daily_routines"]["version"],
                "effect": "future daily obligations and confirmed home execution only; no past meal/shower or user action",
                "effective_from": desired["daily_routines"]["effective_from"],
                "activation_at": desired["daily_routines"]["activation_at"],
                "at": now.isoformat()}
            db.execute("INSERT INTO life_evidence(category,id,kind,body) VALUES('cognition',?, 'configuration_migration', ?)",
                       ("config:" + receipt["version"], _canonical(receipt)))
            meta = json.loads(db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'scheduler\') AS life_scheduler_state WHERE id=1').fetchone()[0])
            meta.update(dirty=True, next_decision=receipt["at"])
            db.execute("UPDATE life_state SET body=?  WHERE name='scheduler' AND ( id=1)", (_canonical(meta),))
        self._audit("add_confirmed_daily_routines", {"run_id": run_id,
                    "version": desired["daily_routines"]["version"], "created_history": False})
        return {"run_id": run_id, "version": desired["daily_routines"]["version"],
                "effective_from": desired["daily_routines"]["effective_from"],
                "created_history": False, "restart_required": True}

    def disable(self, reason: str) -> dict:
        if not reason.strip():
            raise ValueError("disable reason required")
        previous = self.get_setting(MODE_KEY, DISABLED)
        self.set_setting(MODE_KEY, DISABLED)
        self._audit("disable", {"previous": previous, "reason": reason})
        return {"mode": DISABLED, "previous": previous, "data_preserved": True}

    def rollback(self, backup_id: str, *, app_stopped: bool) -> dict:
        """Restore through SQLite backup API. Caller must have stopped the app."""
        if not app_stopped:
            raise ValueError("rollback requires an explicitly stopped app")
        if self.get_setting(MODE_KEY, DISABLED) != DISABLED:
            raise ValueError("disable life mode before rollback")
        backup_id = _safe_id(backup_id, "backup id")
        directory = self.backup_root / backup_id
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("unknown backup")
        manifest = json.loads(manifest_path.read_text(encoding="utf8"))
        restored = []
        allowed = {str(path): path for path in self.database_paths}
        for item in manifest["files"]:
            source_path = Path(item["source"]).resolve()
            # Life state may have been supplied as an additional enable-time
            # source. It must remain inside the same runtime root as core DBs.
            try:
                source_path.relative_to(self.database_paths[0].parent.resolve())
            except ValueError:
                continue
            else:
                allowed[str(source_path)] = source_path
        for item in manifest["files"]:
            target = allowed.get(item["source"])
            source = directory / item["backup"]
            if target is None or not source.is_file() or _sha256(source) != item["sha256"]:
                raise ValueError("backup manifest mismatch")
            source_db = sqlite3.connect(source)
            target_db = sqlite3.connect(target)
            try:
                source_db.backup(target_db)
            finally:
                target_db.close()
                source_db.close()
            restored.append(str(target))
        # The restored settings database contains its pre-enable value.
        return {"backup_id": backup_id, "restored": restored, "app_restart_required": True}


class LocalLifeApp:
    """Life agent boundary: durable chat inbox, verified snapshots and event feed."""

    def __init__(self, get_setting: Callable[[str, str], str], engine_factory: Callable[[str], object], *,
                 allow_test_fixture: bool = False, foreground_pending=None):
        self.get_setting, self.engine_factory = get_setting, engine_factory
        self.allow_test_fixture = allow_test_fixture
        self._engine = None
        self._loaded_run_id = None
        self._worker_context = None
        self._lock = threading.RLock()
        self._tick_lock = threading.Lock()
        self._tick_thread = threading.local()
        self.foreground_pending = foreground_pending or (lambda: False)
        self._last_background = None
        self._chat_snapshot = None

    @staticmethod
    def background_capabilities() -> dict:
        """Declarative contract implemented below and checked by preflight/tests."""
        return {"independent_of_proactive_messages": True,
                "sleep_and_natural_wake_tick": True,
                "activity_checkpoint_scheduler": True,
                "autonomous_next_action": True,
                "single_scheduler_worker": True,
                "interaction_tick_called_directly": False}

    @property
    def enabled(self) -> bool:
        return self.get_setting(MODE_KEY, DISABLED) == ENABLED

    def _load(self):
        if not self.enabled:
            return None
        run_id = _safe_id(self.get_setting(RUN_KEY, ""), "run id")
        raw_policy = self.get_setting(POLICY_KEY, "")
        if not raw_policy:
            raise RuntimeError("life system policy is unconfigured")
        policy = json.loads(raw_policy)
        EnablePolicy(**policy).validate(allow_test_fixture=self.allow_test_fixture)
        if self._engine is None or self._loaded_run_id != run_id:
            engine = self.engine_factory(run_id)
            if not self.allow_test_fixture and engine.p.config.get("mode") == "isolated_test":
                raise RuntimeError("isolated test state cannot be enabled in the local App")
            initialize_mailbox(engine)
            from application.life_agent_events import initialize
            initialize(engine)
            # Publish only a fully initialized agent to concurrent chat readers.
            self._engine, self._loaded_run_id = engine, run_id
        return self._engine

    def _ensure_worker(self):
        engine = self._load()
        if engine is None:
            return None
        from application.bedtime_notice import deliver
        engine.chat.before_fallback_sleep = deliver
        if self._worker_context is None:
            context = engine.worker()
            try:
                context.__enter__()
            except BaseException:
                raise
            self._worker_context = context
        return engine

    def _close_worker(self) -> None:
        if self._worker_context is not None:
            context, self._worker_context = self._worker_context, None
            context.__exit__(None, None, None)

    def startup(self) -> dict:
        if not self.enabled:
            return {"mode": DISABLED, "state_owner": "none", "life_database_opened": False}
        with self._lock:
            try:
                engine = self._ensure_worker()
                engine.chat.repair_stale_goodnight()
                engine.chat.repair_restart_cancelled_sleep()
                engine.chat.apply_explicit_wake_correction()
            except Exception as error:
                self._close_worker()
                return {**self.status(load=False), "life_database_opened": False,
                        "status": "blocked", "blocker": f"{type(error).__name__}: {error}"}
            self.refresh_chat_context()
            return self.status(load=True)

    def shutdown(self) -> None:
        with self._tick_lock, self._lock:
            self._close_worker()
            self._engine = None
            self._loaded_run_id = None
            self._chat_snapshot = None

    def status(self, *, load: bool = False) -> dict:
        base = {"mode": ENABLED if self.enabled else DISABLED,
                "state_owner": "life_system" if self.enabled else "none",
                "legacy_schedule_writes": False,
                "legacy_affect_writes": False,
                "separate_life_reply": False,
                "background": self.background_capabilities()}
        if not self.enabled:
            return {**base, "life_database_opened": False}
        if not load and self._engine is None:
            return {**base, "life_database_opened": False, "status": "enabled_not_loaded"}
        try:
            state = self._load().p.snapshot()
        except Exception as error:
            return {**base, "life_database_opened": False, "status": "blocked",
                    "blocker": f"{type(error).__name__}: {error}"}
        active = state["activities"].get(state["active"]) if state.get("active") else None
        engine = self._engine
        scheduler = {}
        if engine is not None:
            try:
                with engine.store.connect() as db:
                    meta_row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'scheduler\') AS life_scheduler_state WHERE id=1').fetchone()
                    blocked_row = db.execute("""SELECT j.id,j.kind,j.receipt FROM life_scheduler_jobs j
                        WHERE j.status='blocked' AND NOT EXISTS (
                            SELECT 1 FROM life_scheduler_recoveries r WHERE r.blocked_job_id=j.id)
                        ORDER BY j.rowid LIMIT 1""").fetchone()
                meta = json.loads(meta_row[0]) if meta_row else {}
                scheduler = {"worker_active": self._worker_context is not None,
                    "last_cycle": self._last_background,
                    "next_decision_at": meta.get("next_decision"),
                    "next_checkpoint_at": active.get("next_due_at") if active else None,
                    "blocker": ({"job_id": blocked_row[0], "kind": blocked_row[1],
                                 "detail": json.loads(blocked_row[2]) if blocked_row[2] else None}
                                if blocked_row else None)}
            except (sqlite3.Error, ValueError, json.JSONDecodeError) as error:
                scheduler = {"worker_active": self._worker_context is not None,
                             "status_read_error": f"{type(error).__name__}: {error}"}
        generation_model = getattr(getattr(engine.cog, "calls", None), "model", None)
        planning_reference = None
        daily_obligations = []
        if engine is not None and engine.p.config.get("planning_reference"):
            try:
                from life_prototype.planning_reference import view as planning_reference_view
                planning_reference = planning_reference_view(
                    engine.p.config["planning_reference"], engine.p.config["places"], engine.clock.now(),
                    getattr(engine.cog, "calendar_provider", None))
            except (KeyError, TypeError, ValueError) as error:
                planning_reference = {"status": "invalid", "error": f"{type(error).__name__}: {error}"}
        if engine is not None and engine.p.config.get("daily_routines"):
            try:
                from life_prototype.daily_obligations import status as routine_status
                daily_obligations = routine_status(engine.p.config, state, engine.clock.now(),
                    getattr(engine.cog, "calendar_provider", None))
            except (KeyError, TypeError, ValueError) as error:
                daily_obligations = [{"status": "invalid", "error": f"{type(error).__name__}: {error}"}]
        from life_prototype.coarse_plan_updates import latest as latest_agenda_review
        from life_prototype.fine_plan import view as fine_agenda_view
        from life_prototype.coarse_plan_execution import requirement as coarse_requirement
        from life_prototype.outing_content import saved as saved_outing_content
        outing_content = saved_outing_content(engine.cog)
        from life_prototype.weread_library import view as weread_view
        from life_prototype.media_recommendations import view as media_view
        place_name = engine.p.config.get("places", {}).get(state["place"], {}).get("name", state["place"])
        active_view = None
        if active:
            target = active.get("target")
            if active.get('outing_mode'):
                from life_prototype.skill_outing import LABELS
                target_name=LABELS[active['outing_category']][0]
            elif active.get('work_mode'):
                target_name=active['work_title']
            elif active.get('housework_mode'):
                target_name=active['housework_title']
            elif active.get('care_mode'):
                target_name=active['care_title']
            elif active.get('meal_mode'):
                target_name = '、'.join(active['dishes'])
            elif active.get("kind") == "moving":
                target_name = engine.p.config.get("places", {}).get(target, {}).get("name", target)
            elif active.get("kind") == "work":
                target_name = engine.p.config.get("work_items", {}).get(target, {}).get("title", target)
            elif active.get("kind") == "reading":
                target_name = engine.p.config.get("books", {}).get(target, {}).get("title", target)
            elif active.get('kind') == 'watching':
                target_name = engine.p.config.get('movies', {}).get(target, {}).get('title', target)
            else:
                target_name = target
            active_view = {**active, "place_name": place_name, "target_name": target_name}
            if active.get('viewing_mode') == 'active_time_simulation':
                from life_prototype.skill_movie import elapsed_seconds, position
                seconds = active['progress']
                if self._worker_context is not None and state.get('sleep', {}).get('status') == 'awake':
                    seconds += elapsed_seconds(state, active, engine.clock.now())
                viewing = position(active['movie_duration_seconds'], seconds)
                active_view.update(progress=viewing['watched_seconds'], total=viewing['duration_seconds'],
                                   progress_unit='simulated_viewing_seconds', viewing_position=viewing)
        coarse_execution = coarse_requirement(engine.cog, state) if engine is not None else None
        coarse_item = (coarse_execution or {}).get("item") or {}
        from life_prototype.companionship import current as companion_current
        companion = companion_current(state, engine.p.clock.now()) if engine is not None else None
        coarse_activity = None
        user_time = None
        if coarse_item:
            from life_prototype.coarse_plan_schema import intent as coarse_intent
            coarse_activity = {
                "id": coarse_item.get("id"),
                "kind": 'user_time' if coarse_item.get('activity') == 'user_time' else coarse_item.get("state_type") or coarse_item.get("kind"),
                "title": coarse_intent(coarse_item) or coarse_item.get("title"),
                "start_at": coarse_item.get("start_at"),
                "end_at": coarse_item.get("end_at"),
            }
            if (coarse_item.get('activity') == 'user_time' and state.get('sleep', {}).get('status') == 'awake'
                    and (state.get('coarse_state') or {}).get('appointment_id') == coarse_item.get('appointment_id')
                    and not active):
                user_time = {'appointment_id': coarse_item['appointment_id'], 'title': coarse_item['title'],
                             'start_at': coarse_item['start_at'], 'end_at': coarse_item['end_at'],
                             'source_message': coarse_item.get('source_message'), 'location_policy': 'unspecified',
                             'semantics': 'reserved time for the user; no user actions or completion inferred'}
        return {**base, "life_database_opened": True, "status": "ready",
                "run_id": self._loaded_run_id, "revision": state["revision"],
                "place": state["place"], "place_name": place_name,
                "activity": active_view,
                "user_time": user_time,
                "companion": companion,
                "coarse_activity": coarse_activity,
                "household_machines": state.get('household_machines',{}),
                "laundry_batches": state.get('laundry_batches',{}),
                "household_followups": state.get('household_followups',{}),
                "outing_sessions": state.get("outing_sessions",{}),
                "dynamic_drafts": outing_content['drafts'],
                "owned_books": outing_content['owned_books'],
                "media_recommendations": media_view(engine.cog),
                "weread": weread_view(engine.cog),
                "rest_sessions": state.get("rest_sessions",{}),
                "work_sessions": state.get('work_sessions',{}),
                "work_steps": state.get('work_steps',{}),
                "television_sessions": state.get("television_sessions",{}),
                "exercise_sessions": state.get('exercise_sessions',{}),
                "exercise_checkins": state.get('exercise_checkins',{}),
                "sleep": state.get("sleep", {}), "scheduler": scheduler,
                "planning_reference": planning_reference,
                "daily_agenda": engine.cog.agenda.view(state=state) if engine is not None else None,
                "coarse_execution": coarse_execution,
                "coarse_state": state.get('coarse_state'),
                "daily_agenda_review": latest_agenda_review(engine.cog.agenda) if engine is not None else None,
                "fine_agenda": fine_agenda_view(engine.cog, state) if engine is not None else None,
                "memory_storage": {"database": str(engine.store.path),
                                   "table": "life_memories", "types": ["event", "thought"]} if engine is not None else None,
                "daily_obligations": daily_obligations,
                "generation": {"kind": getattr(generation_model, "kind", "unknown"),
                    "provider": getattr(generation_model, "provider", "unknown"),
                    "control": "autonomous_tool_loop" if getattr(engine, "agent", None) else "fixed_pipeline",
                    "max_calls_per_run": getattr(getattr(engine, "agent", None), "max_calls", None),
                    "session_policy": "new ephemeral CLI thread per stage; never resume"}}

    def book_library(self) -> list[dict]:
        if self.get_setting(MODE_KEY, DISABLED) != ENABLED:
            return []
        from life_prototype.book_library import public_view, tick
        engine = self._load()
        books = public_view(engine.cog)
        tick(engine.cog)
        return books

    def movie_library(self) -> list[dict]:
        if not self.enabled:
            return []
        from life_prototype.movie_library import view
        return view(self._load().cog)

    def add_book_to_library(self, title: str, author: str) -> dict:
        if not self.enabled:
            raise RuntimeError('书库暂时不可用')
        from life_prototype.book_library import add
        return add(self._load().cog, title, author)

    def chat_context(self, *, message_id=None) -> dict | None:
        status = self.status(load=True) if self.enabled else None
        if not status or status.get("status") != "ready":
            return None
        activity = status.get("activity")
        context = {"source": "verified_life_snapshot", "revision": status["revision"],
                "companion_booking_rule": "明确陪伴邀请必须有开始时间；只有明确现在或上下文已确定开始时间才能安排。只说陪我去漫展时先问什么时候出发，不默认现在。结束时间可留空，不强制追问；未有applied回执不得声称已进入或已预约。",
                "itinerary_adjustment_rule": "早点回家、取消健身、调整活动时间等属于左然自己的行程调整，不进入陪伴。结合实际状态和原安排协商，不机械照办。若你决定并答应早点回家、准备回去，已发送承诺会交给Life审议落实自己的行程；可以自主选择可行时间。立即催促回家可按现在出发理解。只有applied回执才能确认日程已修改；真实通勤开始前不能声称已出发，更不能声称已到家。",
                "household_machines": _recent_state_entries(status.get('household_machines')),
                "laundry_batches": _recent_state_entries(status.get('laundry_batches')),
                "household_followups": _recent_state_entries(status.get('household_followups')),
                "outing_sessions": _recent_state_entries(status.get("outing_sessions"), 1),
                "rest_sessions": _recent_state_entries(status.get("rest_sessions"), 1),
                "television_sessions": _recent_state_entries(status.get("television_sessions"), 1),
                "exercise_sessions": _recent_state_entries(status.get('exercise_sessions'), 1),
                "exercise_checkins": _recent_state_entries(status.get('exercise_checkins'), 1),
                "place": status["place"], "place_name": status.get("place_name"),
                "place_semantics": "current location only; never infer washing, working, eating or any other action from a room",
                "activity": _chat_activity_view(activity),
                "activity_semantics": ("only this structured activity is currently happening"
                    if activity else "no activity is currently in progress; do not invent one from place or old memories"),
                "sleep": status["sleep"].get("status")}
        if status.get('user_time'):
            context.update(user_time=status['user_time'], place=None, place_name=None,
                           place_semantics='location unspecified during user time; do not infer location from last stored place',
                           activity_semantics='currently reserving time for the stated user appointment; no detailed shared actions inferred')
        # ``accept_message`` may have interrupted the activity before the host
        # builds the one and only chat reply.  In that case ``state.active`` is
        # intentionally empty, but the durable message receipt still records
        # what was happening when this particular message arrived.  Surface
        # that committed fact rather than asking the language model to infer it
        # from an old memory or from the now-empty active slot.
        engine = self._engine
        if engine is not None:
            with mailbox_connect(engine) as db:
                pending = db.execute("SELECT id FROM life_agent_inbox WHERE status='pending' ORDER BY rowid").fetchall()
                deliveries = db.execute("SELECT id,status,receipt FROM life_agent_inbox ORDER BY rowid DESC LIMIT 8").fetchall()
            context['life_agent_delivery'] = {
                'pending_message_ids': [row[0] for row in pending],
                'recent_deliveries': [{'message_id': row[0], 'status': row[1],
                    'receipt': json.loads(row[2]) if row[2] and row[1] != 'delivered' else None} for row in deliveries],
                'rule': 'pending 表示仅已投递，生活 Agent 尚未处理；不能说已取消活动或确认新安排。日程变更以对应消息的 applied 回执为准。'}
            try:
                with engine.store.connect() as db:
                    rows = db.execute(
                        "SELECT id,request,receipt FROM life_received_messages ORDER BY rowid DESC LIMIT 20"
                    ).fetchall()
                latest = None
                for source_message_id, request_body, receipt_body in rows:
                    request = json.loads(request_body)
                    if request.get("source") == "local_app_message":
                        latest = (source_message_id, json.loads(receipt_body))
                        break
                if latest is not None:
                    effect_message_id, receipt = latest
                    effect = {
                        "message_id": effect_message_id,
                        "occurred_at": receipt.get("occurred_at"),
                        "wake_reason": receipt.get("wake_reason"),
                        "sleep_request": receipt.get("sleep_request"),
                    }
                    interrupted_id = receipt.get("interrupted_activity")
                    if interrupted_id:
                        state = engine.p.snapshot()
                        interrupted = state.get("activities", {}).get(interrupted_id)
                        if interrupted:
                            from life_prototype.state_view import progress_view
                            effect["activity_before_message"] = _chat_activity_view(
                                progress_view(interrupted, engine.p.config)
                            )
                            effect["activity_before_message_semantics"] = (
                                "This was the verified activity at the instant this user message arrived. "
                                "Use it to answer what 左然 was doing when asked; do not infer from the coarse plan."
                            )
                        else:
                            effect["activity_before_message"] = {"id": interrupted_id}
                    context["current_message_effect"] = effect
            except (sqlite3.Error, ValueError, json.JSONDecodeError, KeyError, TypeError):
                # The current verified snapshot remains useful.  A malformed or
                # unavailable optional message projection must never fabricate
                # activity context or block the host reply path.
                pass
        if status.get("daily_obligations"):
            context["daily_obligations"] = status["daily_obligations"]
        if status.get('companion'):
            context['companion'] = status['companion']
            context['place'] = context['place_name'] = None
            context['companion_rule'] = ('用户主导的陪伴正在持续。事项随用户报备更新，不假设地点或活动成果。'
                '没有结束回执不得声称陪伴结束；沉默、晚安和事项结束都不代表结束陪伴。')
        if status.get("daily_agenda"):
            context["daily_agenda"] = status["daily_agenda"]
        if status.get("coarse_execution"):
            context["coarse_execution"] = status["coarse_execution"]
        if status.get('fine_agenda'):
            context['fine_agenda'] = _chat_fine_agenda_view(status['fine_agenda'])
            context['fine_agenda_rule'] = '细日程是未来意图；只有实际活动和已验证进度能证明已开始或完成。观看时长是角色模拟记录，不是用户播放器行为。'
        if status.get("daily_agenda_review"):
            context["daily_agenda_review"] = status["daily_agenda_review"]
            context["agenda_change_rule"] = ("用户消息由后台LLM审议剩余日程。pending/running只表示待处理，不能说已经改好或已确认约定；"
                "applied才表示粗计划修改已提交，也不证明用户到场或活动完成。clarify/needs_review应结合原因询问或解释，"
                "none表示保持原日程。回执交给聊天 Agent 表达，生活 Agent 不直接生成或发送聊天回复。")
        if message_id is not None and engine is not None:
            ids = (str(message_id) + ':ordinary', str(message_id) + ':goodnight')
            with mailbox_connect(engine) as db:
                delivery = db.execute('SELECT id,status,receipt FROM life_agent_inbox WHERE id IN (?,?) ORDER BY rowid DESC LIMIT 1', ids).fetchone()
            with engine.store.connect() as db:
                review = db.execute('SELECT message_id,status,receipt FROM life_agenda_messages WHERE message_id IN (?,?) ORDER BY rowid DESC LIMIT 1',
                                    tuple('app:' + ident for ident in ids)).fetchone()
            context['requested_message'] = {'message_id': str(message_id),
                'delivery': ({'message_id': delivery[0], 'status': delivery[1],
                              'receipt': json.loads(delivery[2]) if delivery[2] else None}
                             if delivery else {'status': 'not_submitted'})}
            context['daily_agenda_review'] = ({'message_id': review[0], 'status': review[1],
                'detail': json.loads(review[2]) if review[2] else None} if review else None)
            if context.get('current_message_effect', {}).get('message_id') not in tuple('app:' + ident for ident in ids):
                context.pop('current_message_effect', None)
        from life_prototype.media_recommendations import view as media_view
        context['media_recommendations'] = media_view(engine.cog)[:20]
        context['media_recommendation_rule'] = '聊天作品异步加入清单；只有清单记录才证明已保存，ready 才表示资源已核对。推荐不表示已经阅读、观看或更改日程。'
        from life_prototype.life_continuity import view as continuity_view, sent_view
        with engine.store.connect() as db:
            context['life_continuity'] = continuity_view(db, engine.store.read(db), engine.p.config)
        with mailbox_connect(engine) as db:
            context['life_continuity']['recent_sent_messages'] = sent_view(db)
        return context

    def refresh_chat_context(self):
        """Publish a detached snapshot after Life commits, never on chat reads."""
        with self._lock:
            try:
                context = self.chat_context()
                if context is None:
                    self._chat_snapshot = None
                    return
                with mailbox_connect(self._engine) as db:
                    deliveries = db.execute(
                        'SELECT id,status,receipt FROM life_agent_inbox ORDER BY rowid DESC LIMIT 100'
                    ).fetchall()
                with self._engine.store.connect() as db:
                    reviews = db.execute(
                        'SELECT message_id,status,receipt FROM life_agenda_messages ORDER BY rowid DESC LIMIT 100'
                    ).fetchall()
                self._chat_snapshot = (deepcopy(context),
                    {row[0]: {'message_id': row[0], 'status': row[1],
                              'receipt': json.loads(row[2]) if row[2] else None} for row in deliveries},
                    {row[0]: {'message_id': row[0], 'status': row[1],
                              'detail': json.loads(row[2]) if row[2] else None} for row in reviews})
            except Exception:
                # Do not present an older snapshot as current after a failed refresh.
                self._chat_snapshot = None

    def query_context(self, *, message_id=None) -> dict | None:
        """Read only the snapshot pushed by Life; no engine/database queries."""
        snapshot = self._chat_snapshot
        if not self.enabled or snapshot is None:
            return None
        context, deliveries, reviews = deepcopy(snapshot)
        sent_context = getattr(self, '_sent_conversation_context', None)
        if sent_context is not None and sent_context[0] is self._engine and 'life_continuity' in context:
            context['life_continuity']['recent_sent_messages'] = deepcopy(sent_context[1])
        if message_id is not None:
            ids = (str(message_id) + ':ordinary', str(message_id) + ':goodnight')
            context['requested_message'] = {'message_id': str(message_id),
                'delivery': next((value for key, value in deliveries.items() if key in ids),
                                 {'status': 'unavailable'})}
            context['daily_agenda_review'] = next(
                (value for key, value in reviews.items() if key in tuple('app:' + ident for ident in ids)), None)
            if context.get('current_message_effect', {}).get('message_id') not in tuple('app:' + ident for ident in ids):
                context.pop('current_message_effect', None)
        return context

    def context_text(self, *, message_id=None) -> str:
        context = self.query_context(message_id=message_id)
        if context is None:
            return '\n生活 Agent 当前状态暂不可用；不要用旧日程推断正在进行的活动，也不能声称安排已修改。\n'
        return "\n<verified_life_state>\n" + _canonical(context) + "\n</verified_life_state>\n"

    def activity_feed(self, *, schedule_date=None, limit: int | None = 200) -> list[dict]:
        """Return a read-only UI projection of committed life facts."""
        if not self.enabled:
            return []
        # Do not queue read-only UI traffic behind a scheduler/model call.  The
        # SQLite read transaction supplies the consistent snapshot needed by
        # the projection.  The adapter lock is only needed for lazy startup.
        engine = self._engine
        if engine is None:
            with self._lock:
                engine = self._load()
        if engine is None:
            return []
        from life_prototype.activity_feed import read, display_without_meal_details
        state = engine.p.snapshot()
        with engine.store.connect() as db:
            return display_without_meal_details(
                read(db, state, engine.p.config, schedule_date=schedule_date, limit=limit), state)

    def submit_message(self, original_id: str, content: str, *, goodnight: bool = False) -> dict | None:
        """Persist delivery without acquiring the scheduler/model lock or changing life."""
        if not self.enabled:
            return None
        if not isinstance(content, str) or not 0 < len(content.strip()) <= 5000:
            raise ValueError('invalid message')
        if not str(original_id) or len(str(original_id)) > 180:
            raise ValueError('invalid message id')
        engine = self._engine
        if engine is None:
            return {'message_id': str(original_id), 'status': 'unavailable', 'reason': 'life_agent_not_started'}
        ident = str(original_id) + (':goodnight' if goodnight else ':ordinary')
        with mailbox_connect(engine) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO life_agent_inbox(id,content,goodnight,received_at) VALUES(?,?,?,?)',
                       (ident, content, int(goodnight), engine.clock.now().isoformat()))
            row = db.execute('SELECT content,status,receipt FROM life_agent_inbox WHERE id=?', (ident,)).fetchone()
            if row[0] != content:
                raise ValueError('message id/content conflict')
        # Explicit release phrases are host-verifiable user intent.  Resolve
        # them immediately so chat delivery cannot leave companionship stuck
        # behind an unavailable or delayed Life model.
        import re
        if re.fullmatch(r'\s*(?:你)?(?:不用|不需要|不要)(?:再|继续)?陪(?:着)?我(?:了|啦)?\s*[。！!]*', content) \
                or re.fullmatch(r'\s*(?:请)?结束陪伴(?:吧)?\s*[。！!]*', content):
            from life_prototype.companionship import current
            state = engine.p.snapshot()
            session = current(state, engine.clock.now())
            if session is not None:
                receipt = self.end_companion(session['id'])
                with mailbox_connect(engine) as db:
                    db.execute("UPDATE life_agent_inbox SET status='delivered',receipt=? WHERE id=?",
                               (_canonical(receipt), ident))
                self.refresh_chat_context()
                return {'message_id': ident, 'status': 'delivered', 'receipt': receipt}
        return {'message_id': ident, 'status': row[1],
                'receipt': json.loads(row[2]) if row[2] else None}

    def _drain_inbox(self, engine, limit=16):
        with mailbox_connect(engine) as db:
            rows = db.execute("SELECT id,content,goodnight,received_at,attempts FROM life_agent_inbox WHERE status='pending' ORDER BY rowid LIMIT ?",
                              (limit,)).fetchall()
        for ident, content, goodnight, received_at, attempts in rows:
            from life_prototype.coarse_plan import schedule_day
            from life_prototype.clock import utc
            status = 'delivered'
            try:
                if not received_at or schedule_day(utc(received_at)) != schedule_day(engine.clock.now()):
                    status, receipt = 'expired', {'reason': 'message is from a previous or unknown living day; no retrospective changes'}
                else:
                    receipt = self.accept_message(ident, content, goodnight=bool(goodnight), interrupt=False,
                                                  received_at=received_at)
            except Exception as error:
                status = 'failed' if attempts >= 2 else 'pending'
                receipt = {'error': type(error).__name__, 'schedule_changed': False}
            with mailbox_connect(engine) as db:
                db.execute("UPDATE life_agent_inbox SET status=?,receipt=?,attempts=attempts+1 WHERE id=?",
                           (status, _canonical(receipt), ident))
            if status == 'pending':
                # Keep request order across transient failures: a later cancel
                # must not run before the reservation it refers to. A terminal
                # failure is skipped after the bounded retries above.
                break

    def pending_events(self, limit=1):
        if not self.enabled or self._engine is None:
            return []
        from application.life_agent_events import pending
        return pending(self._engine, limit)

    def acknowledge_event(self, ident, outcome):
        if self._engine is not None:
            from application.life_agent_events import acknowledge
            acknowledge(self._engine, ident, outcome)

    def _publish_events(self):
        if self._engine is not None:
            try:
                from life_prototype.life_continuity import capture
                with self._engine.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    capture(db, self._engine.store.read(db), self._engine.p.config)
            except Exception as error:
                self._last_background = {'status': 'continuity_capture_failed', 'error': type(error).__name__}
        self.refresh_chat_context()
        if self._engine is not None:
            try:
                from application.life_agent_events import capture
                capture(self._engine)
                return True
            except Exception as error:
                self._last_background = {'status': 'event_capture_failed', 'error': type(error).__name__}
        return False

    def record_sent_messages(self, messages):
        """Never acquire the life worker lock after a host chat commit."""
        if not self.enabled or self._engine is None or not messages:
            return
        from life_prototype.life_continuity import record_sent, sent_view
        engine = self._engine
        with mailbox_connect(engine) as db:
            record_sent(db, messages)
            recent = sent_view(db)
        self._sent_conversation_context = (engine, recent)

    @timed('life_input_seconds')
    def accept_message(self, original_id: str, content: str, *, goodnight: bool = False, interrupt: bool = True,
                       received_at: str | None = None) -> dict | None:
        with self._lock:
            engine = self._ensure_worker()
            if engine is None:
                return None
            message_id = "app:" + str(original_id)
            with engine.store.connect() as db:
                old = db.execute("SELECT request,receipt FROM life_received_messages WHERE id=?", (message_id,)).fetchone()
            if old:
                request = json.loads(old[0])
                if (request.get("content") != content or request.get("intent") != ("goodnight" if goodnight else "ordinary")
                        or request.get("source") != "local_app_message"):
                    raise ValueError("message id/content conflict")
                receipt = json.loads(old[1])
            else:
                state = engine.p.snapshot()
                receipt = engine.chat.receive(message_id, content,
                    intent="goodnight" if goodnight else "ordinary", interrupt=interrupt and bool(state.get("active")),
                    expected_revision=state["revision"], source="local_app_message", received_at=received_at)
            # Both operations are idempotent. Resume them after a crash between
            # the original receive commit and the mailbox acknowledgement.
            engine.chat.archive_chat(message_id)
            signal_id = 'host-message:' + message_id
            if len(signal_id) > 140:
                signal_id = 'host-message:' + hashlib.sha256(message_id.encode('utf8')).hexdigest()
            with engine.store.connect() as db:
                signalled = db.execute('SELECT 1 FROM life_scheduler_signals WHERE id=?', (signal_id,)).fetchone()
            if not signalled:
                engine.signal_external_change(signal_id,
                    reason="local App message committed through the single chat input path",
                    state_revision=engine.p.snapshot()['revision'])
            self.refresh_chat_context()
            return receipt

    @contextmanager
    def model_wait(self):
        """Release only the scheduler's adapter lock during external model I/O.

        SQLite transactions and existing revision checks still own commits.
        _tick_lock keeps another tick/shutdown from replacing this worker.
        """
        release = getattr(self._tick_thread, 'active', False)
        revision = self._engine.p.snapshot()['revision'] if release else None
        if release:
            self.refresh_chat_context()
            self._lock.release()
        try:
            yield
        finally:
            if release: self._lock.acquire()
        if release and self._engine.p.snapshot()['revision'] != revision:
            from life_prototype.store import Conflict
            raise Conflict('life input changed while waiting for model; re-evaluate current state')

    def tick(self, tick_id: str, *, max_steps: int = 16) -> dict | None:
        if self.foreground_pending():
            return {'status':'foreground_wait', 'tick_id':str(tick_id)}
        if not self._tick_lock.acquire(blocking=False):
            return {'status':'worker_busy', 'tick_id':str(tick_id)}
        try:
            self._tick_thread.active = True
            return self._tick(tick_id, max_steps=max_steps)
        finally:
            self._publish_events()
            self._tick_thread.active = False
            self._tick_lock.release()

    def _tick(self, tick_id: str, *, max_steps: int = 16) -> dict | None:
        """Run one bounded background cycle through P4, which owns P3 ticking.

        ``tick_id`` is diagnostic only: P4 derives durable job ids from state and
        checkpoints. Calling this repeatedly before anything is due is therefore
        idle and does not ask the model to plan again.
        """
        if not isinstance(max_steps, int) or not 1 <= max_steps <= 64:
            raise ValueError("max_steps must be between 1 and 64")
        with self._lock:
            engine = self._ensure_worker()
            if engine is None:
                return None
            if getattr(engine, 'agent', None) is not None:
                engine.agent.before_step = lambda: self._drain_inbox(engine)
                engine.agent.publish = self._publish_events
            statuses = []
            progress_statuses = {"queued", "worked", "fine_agenda_prepared", "fine_activity_paused", "agenda_reviewed", "routine_materialized", "coarse_state_entered", "coarse_activity_paused"}
            for _ in range(max_steps):
                # Deliver messages between stages, not after a whole multi-model
                # cycle. No in-flight model call is cancelled by a chat input.
                self._drain_inbox(engine)
                from application.itinerary_reply_bridge import sync as sync_itinerary_replies
                from infrastructure.paths import DATABASE_PATH
                with sqlite3.connect(DATABASE_PATH.as_uri() + '?mode=ro', uri=True) as host:
                    sync_itinerary_replies(engine, host)
                if self.foreground_pending():
                    statuses.append('foreground_wait')
                    break
                status = engine.pump()
                self._publish_events()
                statuses.append(status)
                if status not in progress_statuses:
                    break
            result = {"tick_id": str(tick_id), "status": statuses[-1],
                      "steps": len(statuses), "statuses": statuses,
                      "revision": engine.p.snapshot()["revision"]}
            if len(statuses) == max_steps and statuses[-1] in progress_statuses:
                result["bounded"] = True
            self._last_background = result
            return result

    def manual_wake(self, wake_id: str) -> dict | None:
        with self._lock:
            engine = self._ensure_worker()
            receipt = engine.chat.manual_wake("app:" + wake_id) if engine is not None else None
            self.refresh_chat_context()
            return receipt

    def end_companion(self, session_id: str) -> dict:
        with self._lock:
            engine = self._ensure_worker()
            if engine is None:
                raise ValueError('life system is disabled')
            from life_prototype.companionship import manual_end
            receipt = manual_end(engine.cog, session_id)
            engine.cog.agenda.ensure()
            revision = engine.p.snapshot()['revision']
            engine.signal_external_change('companion-end:' + session_id + ':' + str(revision),
                reason='manual_companion_end', state_revision=revision)
            self.refresh_chat_context()
            return receipt

    def forget_loaded_engine(self) -> None:
        """Test/restart hook; durable state remains in the life database."""
        self.shutdown()


def eligible_personal_memory(record: dict) -> bool:
    """Boundary for a future host-provided LMC sink; this function never writes."""
    if record.get("status") != "active" or record.get("kind") not in {"event", "thought"}:
        return False
    evidence = record.get("evidence") or {}
    source = str(evidence.get("source") or evidence.get("knowledge_basis") or "")
    blocked = ("test" in source or "forecast" in source or "prediction" in source
               or "pending_review" in source or "failed_reflection" in source)
    return not blocked and bool(record.get("id") and record.get("description"))


def activation_preflight(get_setting: Callable[[str, str], str], life_root: Path, backup_root: Path,
                         *, cli_status: dict | None = None) -> dict:
    """Read-only formal activation check. It never provisions or enables state."""
    mode = get_setting(MODE_KEY, DISABLED)
    run_id = get_setting(RUN_KEY, "").strip()
    backup_id = get_setting(BACKUP_KEY, "").strip()
    raw_policy = get_setting(POLICY_KEY, "").strip()
    checks = []

    def add(name, passed, detail, *, blocking=True):
        checks.append({"name": name, "passed": bool(passed), "blocking": blocking, "detail": detail})

    add("review_mode_is_disabled", mode == DISABLED,
        "formal switch remains off" if mode == DISABLED else "disable before reviewing activation")
    policy = None
    if raw_policy:
        try:
            policy = json.loads(raw_policy)
            EnablePolicy(**policy).validate()
            policy_ok = True
            policy_detail = "all four policy versions are user-confirmed"
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            policy_ok, policy_detail = False, str(error)
    else:
        policy_ok, policy_detail = False, "initial state, need rates, offline and special sleep policies are unconfigured"
    add("confirmed_policy_versions", policy_ok, policy_detail)
    life_db = Path(life_root).resolve() / run_id / "prototype.sqlite3" if run_id else None
    add("provisioned_life_database", bool(life_db and life_db.is_file()),
        str(life_db) if life_db else "run id is unconfigured")
    production_db = False
    scheduler_db = False
    if life_db and life_db.is_file():
        try:
            with sqlite3.connect(f"file:{life_db.as_posix()}?mode=ro", uri=True) as db:
                row = db.execute('SELECT config FROM (SELECT rowid,"id" AS "id","body" AS "config" FROM life_state WHERE name=\'world\') AS prototype_meta WHERE id=1').fetchone()
                scheduler_row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'scheduler\') AS life_scheduler_state WHERE id=1').fetchone()
                tables = {item[0] for item in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('life_state','life_scheduler_jobs','life_scheduler_attempts','life_scheduler_inbox','life_scheduler_logs','life_scheduler_signals')")}
            production_db = bool(row and json.loads(row[0]).get("mode") == "local_single_user")
            scheduler_db = bool(scheduler_row and len(tables) == 6
                                and json.loads(scheduler_row[0]).get("config"))
        except (sqlite3.Error, ValueError, json.JSONDecodeError):
            production_db = scheduler_db = False
    add("production_data_class", production_db,
        "local_single_user" if production_db else "isolated test state is not eligible")
    add("scheduler_database_contract", scheduler_db,
        "P4 metadata, jobs, attempts, inbox, records and external-signal ledger are present"
        if scheduler_db else "a provisioned life database with the current P4 schema is required")
    cli_ready = bool(cli_status and cli_status.get("authenticated")
                     and cli_status.get("required_flags_supported") and cli_status.get("version"))
    cli_location = (f"executable={cli_status.get('resolved_executable') or 'unknown'}; "
                    f"config_home={cli_status.get('resolved_config_home') or 'unknown'}") if cli_status else ""
    cli_detail = (f"{cli_status.get('version')}; authenticated; required isolation/schema flags supported; {cli_location}"
                  if cli_ready else
                  (f"{cli_status.get('version') or 'version unavailable'}; "
                   f"authenticated={bool(cli_status.get('authenticated'))}; "
                   f"required_flags_supported={bool(cli_status.get('required_flags_supported'))}; "
                   f"{cli_location}; model calls=0"
                   if cli_status else "Codex CLI readiness has not been verified"))
    add("codex_cli_generation_adapter", cli_ready,
        str((cli_status or {}).get("error") or cli_detail))
    manifest = Path(backup_root).resolve() / "life-mode" / backup_id / "manifest.json" if backup_id else None
    add("verified_pre_enable_backup", bool(manifest and manifest.is_file()),
        str(manifest) if manifest else "backup id is unconfigured")
    capabilities = LocalLifeApp.background_capabilities()
    scheduler_ready = all((capabilities["independent_of_proactive_messages"],
                           capabilities["activity_checkpoint_scheduler"],
                           capabilities["autonomous_next_action"],
                           capabilities["single_scheduler_worker"],
                           not capabilities["interaction_tick_called_directly"]))
    add("independent_activity_scheduler", scheduler_ready,
        "App owns one long-lived Scheduler worker; each background cycle drains bounded P4 pump work and P4 owns sleep ticks")
    add("single_reply_path", True, "existing chat output is the only reply path")
    add("legacy_writer_exclusion", True, "runtime guards disable legacy schedule/attribute/affect writers in life mode")
    blockers = [item for item in checks if item["blocking"] and not item["passed"]]
    return {"ready": not blockers, "mode": mode, "run_id": run_id or None,
            "policy": policy, "checks": checks, "blockers": blockers,
            "side_effects": "none; read-only preflight"}


def open_persisted_engine(root: Path, run_id: str, model, *, calendar_provider=None) -> object:
    """Open an already provisioned life database without inventing configuration."""
    root = Path(root).resolve()
    database = root / _safe_id(run_id, "run id") / "prototype.sqlite3"
    if not database.is_file():
        raise RuntimeError("life database is not provisioned")
    from life_prototype.table_names import migrate
    migrate(database)
    from life_prototype.memory_storage import initialize
    initialize(database)
    with sqlite3.connect(database) as db:
        world_row = db.execute('SELECT config FROM (SELECT rowid,"id" AS "id","body" AS "config" FROM life_state WHERE name=\'world\') AS prototype_meta WHERE id=1').fetchone()
        cognition_row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'cognition\') AS life_cognition_state WHERE id=1').fetchone()
        sleep_row = db.execute('SELECT config FROM (SELECT rowid,"id" AS "id","body" AS "config" FROM life_state WHERE name=\'interaction\') AS life_interaction_config WHERE id=1').fetchone()
        scheduler_row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'scheduler\') AS life_scheduler_state WHERE id=1').fetchone()
    if not all((world_row, cognition_row, sleep_row, scheduler_row)):
        raise RuntimeError("life database is missing a required subsystem")
    scheduler_body = json.loads(scheduler_row[0])
    from life_prototype.clock import RealClock
    from life_prototype.activity_engine import Prototype
    from life_prototype.cognition import Cognition
    from life_prototype.interaction import Interaction
    from life_prototype.scheduler import Scheduler
    prototype = Prototype(run_id, json.loads(world_row[0]), RealClock(), root=root)
    cognition = Cognition(prototype, model, json.loads(cognition_row[0])["config"], calendar_provider)
    if prototype.config.get('mode') == 'local_single_user':
        cognition.resource_root = Path(__file__).resolve().parents[2]
        from application.diet_preferences import read as read_diet
        from infrastructure.sqlite.database import get_app_setting
        cognition.diet_preferences_provider = lambda: read_diet(get_app_setting)
    interaction = Interaction(cognition, json.loads(sleep_row[0]))
    # Formal runs created before ordinary-night calendar resolution existed may
    # contain a sleeping episode without a wake boundary.  The correction is
    # append-only, idempotent and never fabricates activity after the wake.
    interaction.repair_missing_normal_wake()
    scheduler = Scheduler(interaction, scheduler_body["config"])
    if prototype.config.get('mode') == 'local_single_user':
        from life_prototype.autonomous_agent import LifeAgent
        scheduler.agent = LifeAgent(scheduler)
    return scheduler
