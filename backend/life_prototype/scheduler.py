"""Checkpoint scheduler: project adaptation, not a GA/D2A research component.

One OS-locked worker per isolated run; other processes may only enqueue inputs.
No production imports, implicit offline simulation, delivery, or fixed choices.
"""
from contextlib import contextmanager
from datetime import timedelta
import json
import os
import time
import uuid

from .clock import TestClock, utc
from .config import canonical, digest
from .activity_engine import require
from .store import Conflict


DEFAULTS = {"source": "test_fixture_not_persona", "poll_seconds": 1,
            "sleep_checkpoint_seconds": 1800, "idle_check_seconds": 900,
            "max_attempts": 3, "retry_seconds": 5}


class Scheduler:
    def __init__(self, interaction, config=None):
        self.chat, self.cog, self.p = interaction, interaction.cog, interaction.p
        self.store, self.clock = self.p.store, self.p.clock
        self.config = dict(DEFAULTS if config is None else config)
        require(self.config.keys() == DEFAULTS.keys() and self.config["source"] in {
            DEFAULTS["source"], "project_adaptation_local_single_user"}, "explicit P4 configuration required")
        for key in DEFAULTS.keys() - {"source"}:
            require(type(self.config[key]) in (int, float) and self.config[key] > 0, "invalid scheduler timing/budget")
        require(type(self.config["max_attempts"]) is int and self.config["max_attempts"] <= 3, "retry budget is at most three")
        self.session = None
        self.agent = None
        with self.store.connect() as db:
            db.executescript('\n                CREATE TABLE IF NOT EXISTS life_scheduler_jobs(id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,\n                    status TEXT NOT NULL, attempts INTEGER NOT NULL, retry_at TEXT, receipt TEXT);\n                CREATE TABLE IF NOT EXISTS life_scheduler_attempts(id TEXT PRIMARY KEY, job_id TEXT NOT NULL,\n                    started_at TEXT NOT NULL, ended_at TEXT, status TEXT NOT NULL, detail TEXT);\n                CREATE TABLE IF NOT EXISTS life_scheduler_inbox(id TEXT PRIMARY KEY, due_at TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL);\n                CREATE TABLE IF NOT EXISTS life_scheduler_logs(id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL);\n                CREATE TABLE IF NOT EXISTS life_scheduler_recoveries(id TEXT PRIMARY KEY, blocked_job_id TEXT UNIQUE NOT NULL,\n                    replacement_job_id TEXT UNIQUE NOT NULL, request TEXT NOT NULL, receipt TEXT NOT NULL);\n                CREATE TABLE IF NOT EXISTS life_scheduler_signals(id TEXT PRIMARY KEY, body TEXT NOT NULL, receipt TEXT NOT NULL)')
            db.execute("BEGIN IMMEDIATE")
            row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'scheduler\') AS life_scheduler_state WHERE id=1').fetchone()
            if row:
                require(json.loads(row[0])["config"] == self.config, "P4 config changed; use a new run")
            else:
                self._save(db, {"config": self.config, "last_seen": None, "session": None,
                    "next_decision": self.clock.now().isoformat(), "dirty": True, "seen_commitments": [], "stopped": False})

    @staticmethod
    def _meta(db):
        return json.loads(db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'scheduler\') AS life_scheduler_state WHERE id=1').fetchone()[0])

    @staticmethod
    def _save(db, body):
        db.execute("INSERT OR REPLACE INTO life_state(name,id,body) VALUES('scheduler',1,?)", (canonical(body),))

    def _record(self, db, kind, body):
        # Runtime scheduler diagnostics belong in process logs, not the
        # durable life database.  Persistent growth here previously dwarfed
        # the actual state and event records.
        return None

    def _decision_basis(self, state):
        """Hash only facts whose change can make an idle decision materially new.

        Wall-clock seconds are deliberately excluded.  Time-window categories are
        included, so crossing a meal, shower, workday, or calendar boundary still
        wakes cognition.  This is scheduler deduplication, not a model decision or
        an inferred life event.
        """
        with self.store.connect() as db:
            row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'cognition\') AS life_cognition_state WHERE id=1').fetchone()
            cognition_revision = json.loads(row[0])["revision"] if row else None
        obligations = []
        if self.p.config.get("daily_routines"):
            from .daily_obligations import status as routine_status
            obligations = [{k: item.get(k) for k in (
                "id", "kind", "meal", "status", "required", "required_before_sleep")}
                for item in routine_status(self.p.config, state, self.clock.now(),
                                           getattr(self.cog, "calendar_provider", None))]
        planning = None
        if self.p.config.get("planning_reference"):
            reference = self.cog.planning_reference(self.clock.now())["computed"]
            planning = {k: reference.get(k) for k in (
                "relevant_ordinary_workday", "arrival_window_status", "current_day",
                "relevant_workday", "calendar_exception_checked")}
        return digest({"state_revision": state["revision"],
                       "cognition_revision": cognition_revision,
                       "daily_obligations": obligations,
                       "planning_window": planning,
                       "daily_agenda": self._agenda_basis()})

    def _agenda_basis(self):
        agenda = self.cog.agenda.view()
        if not agenda:
            return None
        current = agenda.get("current_item")
        from .fine_plan import current as fine_current
        fine = fine_current(self.cog)
        return {"revision": agenda["evidence_id"], "item": current["id"] if current else None,
                "fine_item": fine['id'] if fine else None}

    def _refresh_daily_routines(self):
        """Expose a general meal as a resource, never as an eating result."""
        if not self.p.config.get("daily_routines"):
            return False
        from .skill_dining import enabled as meal_enabled
        if meal_enabled(self.cog):
            return False  # The saved meal decision now owns food and its location.
        from .daily_obligations import descendant, status
        now = self.clock.now()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self.store.read(db)
            rows = status(self.p.config, state, now, getattr(self.cog, "calendar_provider", None))
            created = []
            for row in rows:
                if row["kind"] != "meal" or row["status"] not in {"due", "overdue"} or row["id"] in state["meals"]:
                    continue
                if descendant(self.p.config, state["place"], "home"):
                    place = self.p.config["household_world"]["dining_place"]
                elif descendant(self.p.config, state["place"], "firm"):
                    place = "firm.office"
                else:
                    continue
                units = self.p.config["daily_routines"]["meal_units"][row["meal"]]
                state["meals"][row["id"]] = {"remaining": units, "place": place,
                    "source": "user_confirmed_general_meal", "meal": row["meal"],
                    "date": row["date"], "resource_model": row["resource_model"]}
                created.append({"id": row["id"], "meal": row["meal"], "place": place,
                                "remaining": units, "result": "available_not_eaten"})
            if not created:
                return False
            prior_revision = state["revision"]
            state["revision"] += 1; state["as_of"] = now.isoformat()
            db.execute("UPDATE life_state SET body=?  WHERE name='current' AND ( id=1)", (canonical(state),))
            for item in created:
                event_id = "p4:routine-available:" + item["id"]
                request = {"operation": "routine_meal_available", "payload": item,
                           "expected_revision": prior_revision}
                receipt = {"event_id": event_id, "revision": state["revision"],
                           "occurred_at": now.isoformat(), "recorded_at": now.isoformat(),
                           "applied_at": now.isoformat(), "source": "user_confirmed_daily_routine"}
                from .event_store import append
                append(db, event_id, request, receipt, state, self.p.config)
            meta = self._meta(db); meta["dirty"] = True; meta["next_decision"] = now.isoformat(); self._save(db, meta)
        return True

    def enqueue(self, input_id, due_at, body):
        """Durable test input. Not a fabricated user action or outbound message."""
        require(isinstance(input_id, str) and 0 < len(input_id) <= 100, "input id required")
        require(body.get("type") in {"message", "failure", "interrupt"}, "unsupported test input")
        require(body.get("source") in {"explicit_test_fixture","isolated_bridge_fixture"}, "input provenance required")
        due_at = utc(due_at).isoformat()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT due_at,body FROM life_scheduler_inbox WHERE id=?", (input_id,)).fetchone()
            require(not old or old == (due_at, canonical(body)), "input id/content conflict")
            db.execute("INSERT OR IGNORE INTO life_scheduler_inbox VALUES(?,?,?,'pending')", (input_id, due_at, canonical(body)))

    def signal_external_change(self, signal_id, *, reason, state_revision):
        """Wake decision scheduling after host-owned input without executing it again."""
        require(isinstance(signal_id, str) and 0 < len(signal_id) <= 140, "signal id required")
        body = {"reason": reason, "state_revision": state_revision,
                "effect": "reassess after necessary host state commit; no result settlement"}
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT body,receipt FROM life_scheduler_signals WHERE id=?", (signal_id,)).fetchone()
            if old:
                require(old[0] == canonical(body), "signal id/content conflict")
                return json.loads(old[1])
            state = self.store.read(db)
            require(state["revision"] == state_revision, "external change signal has stale state revision")
            meta = self._meta(db)
            meta.update(dirty=True, next_decision=self.clock.now().isoformat())
            receipt = {"signal_id": signal_id, "revision": state_revision,
                       "at": self.clock.now().isoformat(), "dirty": True}
            self._save(db, meta)
            db.execute("INSERT INTO life_scheduler_signals VALUES(?,?,?)",
                       (signal_id, canonical(body), canonical(receipt)))
            self._record(db, "external_change", {**body, **receipt})
            return receipt

    @contextmanager
    def worker(self, *, frozen_test_resume=False):
        """OS lock survives long model calls and is released on process death."""
        require(self.session is None, "worker already open")
        path = self.store.path.parent / "p4-worker.lock"
        require(path.resolve() == path.absolute() and (not path.exists() or path.stat().st_nlink == 1), "redirected worker lock")
        handle = open(path, "a+b")
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0"); handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise Conflict("another isolated scheduler owns this run") from None
            self.session = uuid.uuid4().hex
            try:
                self._open_session(frozen_test_resume=frozen_test_resume)
                yield self
            finally:
                with self.store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    meta = self._meta(db)
                    # last_seen is the last completed pump, not an invented checkpoint at exit.
                    meta["stopped"] = True
                    self._save(db, meta)
                    # Reuse the snapshot under the existing writer transaction.
                    # Opening a second SQLite connection here can self-deadlock
                    # during App shutdown on Windows.
                    self._record(db, "worker_stopped", {"session": self.session,
                                                        "state": self.store.read(db)})
                self.session = None
        finally:
            handle.close()

    def _recover(self, db, meta, reason):
        state = self.store.read(db)
        now = self.clock.now()
        begin = meta["last_seen"] or state["as_of"]
        require(now >= utc(begin), "clock moved backwards; recovery requires review")
        self.p._commit_locked(db, "p4:recover:" + self.session + ":" + str(state["revision"]), {
            "operation": "recover", "payload": {"reason": reason}, "expected_revision": state["revision"]}, None)
        state = self.store.read(db)
        # P1's as_of may be older than heartbeat; explicitly report both bounds.
        fact = {"last_worker_check": begin, "resumed_at": now.isoformat(),
                "policy": "no_backfill", "reason": reason, "unobserved_experiences": None}
        if state["sleep"]["status"] == "sleeping":
            episode = self.chat._episode(state)
            # A process gap does not cancel an explicit goodnight. Keep the
            # durable sleeping state, while granting no elapsed sleep credit
            # for the unobserved interval.
            episode["settled_until"] = now.isoformat()
            fact["sleep_continuity"] = "sleeping state preserved; runtime gap not credited"
        self.chat._event(db, state, "p4:gap:" + self.session + ":" + str(state["revision"]),
                         "runtime_gap", fact, now)
        # A queued check is not an actual result. Invalidate only unfinished reads
        # with no staged/settled result; retained P1 results still require review.
        for job_id, attempts in db.execute("SELECT id,attempts FROM life_scheduler_jobs WHERE kind IN ('read','work','world') AND status IN ('pending','running')").fetchall():
            has_result = any(db.execute("SELECT 1 FROM results WHERE id=?", (job_id+":attempt:"+str(n)+":result",)).fetchone()
                             for n in range(1, attempts+1))
            has_result = has_result or any(db.execute("SELECT 1 FROM (SELECT rowid,id,request,receipt FROM life_receipts WHERE category='event_control') WHERE id=?", ("world-failure:"+job_id+":attempt:"+str(n),)).fetchone()
                                          for n in range(1, attempts+1))
            if not has_result:
                db.execute("UPDATE life_scheduler_jobs SET status='done',receipt=? WHERE id=?",
                           (canonical({"cancelled": "restart invalidated checkpoint; no actual result", "gap": fact}), job_id))
                db.execute("UPDATE life_scheduler_attempts SET status='abandoned_on_restart',ended_at=? WHERE job_id=? AND status='running'",
                           (now.isoformat(), job_id))
        meta.update(dirty=True, next_decision=now.isoformat())
        self._record(db, "gap", {**fact, "state": state})

    def _open_session(self, *, frozen_test_resume=False):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            meta = self._meta(db)
            # First adoption of existing P1–P3 also cannot assume offline continuity.
            last = meta["last_seen"]
            if frozen_test_resume:
                require(isinstance(self.clock, TestClock) and last is not None and utc(last) == self.clock.now(),
                        "frozen test resume requires exact saved test time; never a real-time offline policy")
                self._record(db, "frozen_test_resume", {"saved_test_time": last,
                    "wall_time_not_simulated": True, "authorization": "explicit operator continuation of paused test world"})
            elif last is not None or self.p.snapshot()["revision"] > 2:
                self._recover(db, meta, "worker restart/adoption; unobserved interval not simulated")
            meta.update(session=self.session, stopped=False, last_seen=self.clock.now().isoformat())
            self._save(db, meta)
            self._record(db, "worker_started", {"session": self.session, "config": self.config})
        # Refresh versioned library metadata before resuming any pending decision.
        # A long model job must not keep an obsolete reading resource mode alive.
        if getattr(self.cog, 'resource_root', None):
            from .resource_library import sync
            sync(self.cog, self.cog.resource_root)

    def recover_blocked(self, review_id, job_id, reason):
        """Explicit operator-authorized new bounded attempt chain; old rows immutable."""
        require(self.session is not None, "recovery requires worker lock")
        require(bool(review_id) and bool(reason.strip()), "review id and reason required")
        request = {"job_id": job_id, "reason": reason, "authorization": "explicit_user_requested_P4_revalidation"}
        replacement = "p4:review:" + digest([review_id, job_id])[:24]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT request,receipt FROM life_scheduler_recoveries WHERE id=?", (review_id,)).fetchone()
            if old:
                require(old[0] == canonical(request), "recovery id/content conflict")
                return json.loads(old[1])
            row = db.execute("SELECT * FROM life_scheduler_jobs WHERE id=?", (job_id,)).fetchone()
            require(row is not None and row[3] == "blocked", "only blocked jobs may be reviewed")
            require(row[1] in {"message", "decision", "sync", "read", "work"}, "P1 pending results require their own explicit review")
            if row[1] in {"read", "work"}:
                require(not db.execute("SELECT 1 FROM results WHERE receipt IS NULL").fetchone(),
                        "P1 pending results require their own explicit review")
                prefix = job_id + ":attempt:"
                require(not db.execute("SELECT 1 FROM results WHERE substr(id,1,?)=?",
                                       (len(prefix), prefix)).fetchone(),
                        "reading task already staged a result; reconcile its receipt before retry")
            require(not db.execute("SELECT 1 FROM life_scheduler_recoveries WHERE blocked_job_id=?", (job_id,)).fetchone(),
                    "job already has a recovery; review its replacement separately")
            receipt = {"review_id": review_id, "blocked_job_id": job_id, "replacement_job_id": replacement,
                       "prior_attempts": row[4], "new_max_attempts": self.config["max_attempts"],
                       "reviewed_revision": self.store.read(db)["revision"], "at": self.clock.now().isoformat()}
            db.execute("INSERT INTO life_scheduler_jobs VALUES(?,?,?,'pending',0,NULL,NULL)", (replacement, row[1], row[2]))
            db.execute("INSERT INTO life_scheduler_recoveries VALUES(?,?,?,?,?)",
                       (review_id, job_id, replacement, canonical(request), canonical(receipt)))
            self._record(db, "explicit_blocked_recovery", {**receipt, "reason": reason})
            return receipt

    def _job(self, kind, key, payload):
        job_id = "p4:" + kind + ":" + digest(key)[:24]
        with self.store.connect() as db:
            if kind in {'read', 'work', 'world'} and not payload:
                state = self.store.read(db)
                active = state['activities'].get(state.get('active'))
                payload = {'checkpoint_basis': {k: active.get(k) for k in ('id', 'revision', 'progress')} if active else None}
            db.execute("INSERT OR IGNORE INTO life_scheduler_jobs VALUES(?,?,?,'pending',0,NULL,NULL)",
                       (job_id, kind, canonical(payload)))
        return job_id

    def _advance_sleep(self, state):
        """Deterministic sleep timing does not wait behind failed model work."""
        episode = self.chat._episode(state)
        due = utc(episode['settled_until']) + timedelta(seconds=self.config['sleep_checkpoint_seconds'])
        if episode['natural_wake_at']:
            due = min(due, utc(episode['natural_wake_at']))
        if self.clock.now() < due:
            return 'idle_sleep'
        key = episode['id'] + ':' + episode['settled_until']
        job_id = self._job('sleep', key, {'id': 'p4:' + digest(key)[:24]})
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM life_scheduler_jobs WHERE id=?', (job_id,)).fetchone()
        return self._run_job(row)

    def _retry_blocked(self, row):
        """Retry fresh cognition after cooldown, never replay uncertain results.

        Each chain retains its three-attempt limit and immutable audit. Backoff
        survives restarts; repeated outages reach one chain per hour.
        """
        job_id, kind, raw, _, _, _, receipt = row
        if kind not in {'decision', 'sync', 'read', 'work', 'world', 'agent_message'}:
            return 'blocked'
        detail = json.loads(receipt) if receipt else {}
        error = str(detail).lower()
        if any(x in error for x in ('http 401', 'http 402', 'http 403', 'insufficient_quota',
                                    'invalid api key', 'requires_explicit', 'provider_block',
                                    'blocked pending operator review')):
            return 'blocked'
        now = self.clock.now()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM life_scheduler_jobs WHERE id=?', (job_id,)).fetchone()
            if current != row:
                return 'retry_wait'
            if db.execute('SELECT 1 FROM life_scheduler_recoveries WHERE blocked_job_id=?', (job_id,)).fetchone():
                return 'queued'
            # An existing result (even a committed one with a missing job
            # receipt) must be reconciled, not recomputed under a new ID.
            if db.execute("SELECT 1 FROM result_controls WHERE status='pending'").fetchone():
                return 'blocked'
            prefix = job_id + ':attempt:'
            if db.execute('SELECT 1 FROM results WHERE substr(id,1,?)=?', (len(prefix), prefix)).fetchone():
                return 'blocked'
            failure_prefix = 'world-failure:' + prefix
            if db.execute("SELECT 1 FROM life_receipts WHERE category='event_control' AND substr(id,1,?)=?",
                          (len(failure_prefix), failure_prefix)).fetchone():
                return 'blocked'
            parent = db.execute('SELECT request FROM life_scheduler_recoveries WHERE replacement_job_id=?',
                                (job_id,)).fetchone()
            round_number = (json.loads(parent[0]).get('automatic_round', 0) if parent else 0) + 1
            delay = (60, 300, 900, 3600)[min(round_number-1, 3)]
            if not detail.get('automatic_retry_at'):
                detail['automatic_retry_at'] = (now + timedelta(seconds=delay)).isoformat()
                detail['automatic_round'] = round_number
                db.execute('UPDATE life_scheduler_jobs SET receipt=?,retry_at=? WHERE id=?',
                           (canonical(detail), detail['automatic_retry_at'], job_id))
                return 'retry_wait'
            if now < utc(detail['automatic_retry_at']):
                return 'retry_wait'
            review_id = 'auto:' + job_id
            replacement = 'p4:auto:' + digest(job_id)[:24]
            request = {'job_id': job_id, 'authorization': 'automatic_safe_retry',
                       'automatic_round': round_number, 'cooldown_seconds': delay}
            result = {'review_id': review_id, 'blocked_job_id': job_id, 'replacement_job_id': replacement,
                      'at': now.isoformat(), 'automatic': True, 'no_activity_result_replayed': True}
            db.execute("INSERT INTO life_scheduler_jobs VALUES(?,?,?,'pending',0,NULL,NULL)",
                       (replacement, kind, raw))
            db.execute('INSERT INTO life_scheduler_recoveries VALUES(?,?,?,?,?)',
                       (review_id, job_id, replacement, canonical(request), canonical(result)))
            return 'queued'

    def _execute(self, kind, payload, attempt):
        if kind in {'read', 'work', 'world'}:
            state = self.p.snapshot()
            active = state['activities'].get(state.get('active'))
            basis = payload.get('checkpoint_basis')
            if not active or (basis and any(active.get(k) != value for k, value in basis.items())):
                return {'checkpoint_superseded': True, 'no_result_committed': True}
        if kind == "message":
            self.chat.receive(payload["id"], **payload["message"])
            # Necessary settlement runs outside optional expression handling.
            self.cog.synchronize(attempt+':necessary-sync')
            try:
                reply = self.chat.reply(payload["id"], attempt)
            except Conflict:
                raise
            except ValueError as exc:
                with self.store.connect() as db:
                    row = db.execute('SELECT kind,status FROM life_cognition_runs WHERE id=?',(attempt,)).fetchone()
                    if row != ('p3_reply:'+payload['id'],'rejected'): raise
                    review = {'message_id':payload['id'],'status':'pending_review','error':str(exc),
                              'effect':'no reply published; necessary message state retained', 'attempt':attempt}
                    db.execute("INSERT INTO life_evidence(category,id,kind,body) VALUES('cognition',?,'chat_prose_review',?)",(attempt+':prose-review',canonical(review)))
                reply = review
            self.chat.archive_chat(payload["id"])
            return reply
        if kind in {"failure", "interrupt"}:
            return self.p.command(payload["id"], payload["revision"], "fail" if kind == "failure" else "interrupt",
                                  activity_id=payload["activity_id"], reason=payload["reason"])
        if kind == "sleep":
            return self.chat.tick(payload["id"])
        if kind == "sync":
            self.cog.synchronize(attempt)
            return {"observations_absorbed": True}
        if kind == "decision":
            if self.agent is not None:
                return self.agent.run(attempt.rsplit(':attempt:', 1)[0])
            return self.cog.decide(attempt)
        if kind == 'agent_message':
            return self.agent.run(attempt.rsplit(':attempt:', 1)[0], message_id=payload['message_id'])
        if kind == "work":
            from .coarse_plan_execution import pause_mismatch
            if pause_mismatch(self.cog): return {'coarse_action_interrupted': True}
            from .work_artifacts import checkpoint
            return checkpoint(self.cog, attempt)
        if kind == "read":
            from .coarse_plan_execution import pause_mismatch
            if pause_mismatch(self.cog): return {'coarse_action_interrupted': True}
            return self.cog.read_checkpoint(attempt)
        if kind == "world":
            if self.p.config.get('mode') == 'local_single_user' and not self.p.snapshot().get('active'):
                return {'obsolete_checkpoint': True, 'activity_result_created': False}
            from .coarse_plan_execution import pause_mismatch
            if pause_mismatch(self.cog): return {'coarse_action_interrupted': True}
            from .home_world import checkpoint
            return checkpoint(self.p, attempt)
        raise ValueError("executor unavailable; no automatic success")

    def _run_job(self, row):
        # Message dispatch may still refer to its original stable job ID after
        # recovery. Follow the durable chain instead of recreating it.
        with self.store.connect() as db:
            seen = set()
            while row[3] == 'blocked':
                require(row[0] not in seen, 'scheduler recovery cycle')
                seen.add(row[0])
                replacement = db.execute('SELECT replacement_job_id FROM life_scheduler_recoveries WHERE blocked_job_id=?',
                                         (row[0],)).fetchone()
                if not replacement:
                    break
                row = db.execute('SELECT * FROM life_scheduler_jobs WHERE id=?', replacement).fetchone()
                require(row is not None, 'scheduler recovery target missing')
        job_id, kind, raw, status, count, retry_at, _ = row
        if status == 'done':
            return 'worked'
        if status == 'blocked':
            attempt = job_id + ':attempt:' + str(count)
            with self.store.connect() as db:
                committed = db.execute("SELECT receipt FROM life_cognition_runs WHERE id=? AND status='committed'", (attempt,)).fetchone()
            if committed and committed[0]:
                return self._finish_job(job_id, kind, json.loads(raw), attempt, json.loads(committed[0]))
            return self._retry_blocked(row)
        if retry_at and self.clock.now() < utc(retry_at):
            return "retry_wait"
        # Recover a committed cognitive operation before creating any new attempt.
        if status == "running":
            attempt = job_id + ":attempt:" + str(count)
            with self.store.connect() as db:
                prior = db.execute("SELECT status,receipt FROM life_cognition_runs WHERE id=?", (attempt,)).fetchone()
            if prior and prior[0] == "committed":
                return self._finish_job(job_id, kind, json.loads(raw), attempt, json.loads(prior[1]))
            if kind in {"read", "world", "work"}:
                with self.store.connect() as db:
                    settled = db.execute("SELECT receipt FROM results WHERE id=?", (attempt+":result",)).fetchone()
                    if kind == "world" and not settled:
                        settled = db.execute("SELECT receipt FROM (SELECT rowid,id,request,receipt FROM life_receipts WHERE category='event_control') WHERE id=?", ("world-failure:"+attempt,)).fetchone()
                if settled and settled[0]:
                    # Crash after P1 settled, before P2 run receipt: do not read again.
                    if kind in {'read','work'}:
                        with self.store.connect() as db:
                            db.execute('BEGIN IMMEDIATE')
                            frozen=db.execute('SELECT kind FROM life_cognition_runs WHERE id=?',(attempt,)).fetchone()
                            require(frozen is not None and frozen[0]==('reading' if kind=='read' else 'work'),'committed result missing cognitive source')
                            event=db.execute('SELECT receipt FROM (SELECT rowid,id,request,receipt FROM life_receipts WHERE category=\'event_control\') WHERE id=?',('result:'+attempt+':result',)).fetchone()
                            require(event and event[0]==settled[0],'committed result/ledger receipt conflict')
                            self.cog._finish(db,attempt,json.loads(settled[0]))
                    return self._finish_job(job_id, kind, json.loads(raw), attempt, json.loads(settled[0]))
            with self.store.connect() as db:
                db.execute("UPDATE life_scheduler_attempts SET status='abandoned_on_restart',ended_at=? WHERE id=?",
                           (self.clock.now().isoformat(), attempt))
        if count >= self.config["max_attempts"]:
            with self.store.connect() as db:
                db.execute("UPDATE life_scheduler_jobs SET status='blocked' WHERE id=?", (job_id,))
            return "blocked"
        # Never bypass or blindly replace a P1 pending result, even after crash.
        if kind in {"read", "world", "work"}:
            with self.store.connect() as db:
                pending = db.execute("SELECT result_id FROM result_controls WHERE status='pending'").fetchall()
            if pending:
                with self.store.connect() as db:
                    db.execute("UPDATE life_scheduler_jobs SET status='blocked',receipt=? WHERE id=?",
                               (canonical({"requires_explicit_P1_result_review": pending}), job_id))
                return "blocked"
        count += 1
        attempt = job_id + ":attempt:" + str(count)
        with self.store.connect() as db:
            db.execute("UPDATE life_scheduler_jobs SET status='running',attempts=? WHERE id=?", (count, job_id))
            db.execute("INSERT INTO life_scheduler_attempts VALUES(?,?,?,NULL,'running',NULL)",
                       (attempt, job_id, self.clock.now().isoformat()))
        try:
            receipt = self._execute(kind, json.loads(raw), attempt)
            return self._finish_job(job_id, kind, json.loads(raw), attempt, receipt)
        except Exception as exc:
            superseded = isinstance(exc, Conflict) and kind in {'decision','sync','read','work'}
            if superseded and kind in {'read','work'}:
                with self.store.connect() as db:
                    # Never discard a staged result or its required review.
                    superseded = not db.execute('SELECT 1 FROM results WHERE id=?',(attempt+':result',)).fetchone()
            if superseded:
                # A chat interruption supersedes an intention, not a failed life
                # action. Keep its audit, then decide from the new revision.
                with self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    detail=canonical({'superseded':str(exc),'no_new_action_or_checkpoint_committed':True})
                    db.execute("UPDATE life_scheduler_attempts SET status='superseded',ended_at=?,detail=? WHERE id=?",
                               (self.clock.now().isoformat(),detail,attempt))
                    db.execute("UPDATE life_scheduler_jobs SET status='done',receipt=?,retry_at=NULL WHERE id=?",(detail,job_id))
                    meta=self._meta(db)
                    meta.update(dirty=True,next_decision=self.clock.now().isoformat())
                    self._save(db,meta)
                return 'worked'
            # All retry attempts have separate immutable P2 calls; no fallback text.
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                error = {"type": type(exc).__name__, "detail": str(exc)}
                db.execute("UPDATE life_scheduler_attempts SET status='failed',ended_at=?,detail=? WHERE id=?",
                           (self.clock.now().isoformat(), canonical(error), attempt))
                db.execute("UPDATE life_scheduler_jobs SET status=?,retry_at=?,receipt=? WHERE id=?", (
                    "blocked" if count >= self.config["max_attempts"] else "pending",
                    (self.clock.now()+timedelta(seconds=self.config["retry_seconds"]*count)).isoformat(), canonical(error), job_id))
                self._record(db, "failed_attempt", {"job": job_id, "attempt": attempt, **error, "state": self.store.read(db)})
            return "blocked" if count >= self.config["max_attempts"] else "retry_wait"

    def _finish_job(self, job_id, kind, payload, attempt, receipt):
        if kind == "message":
            self.chat.archive_chat(payload["id"])  # also repairs a crash after reply commit
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE life_scheduler_jobs SET status='done',receipt=?,retry_at=NULL WHERE id=?", (canonical(receipt), job_id))
            db.execute("UPDATE life_scheduler_attempts SET status='committed',ended_at=?,detail=? WHERE id=?",
                       (self.clock.now().isoformat(), canonical(receipt), attempt))
            meta = self._meta(db)
            if kind in {"message", "failure", "interrupt"}:
                db.execute("UPDATE life_scheduler_inbox SET status='done' WHERE id=?", (payload["id"],))
                meta["dirty"] = True
            if kind == "sleep" and receipt.get("wake_reason"):
                meta["dirty"] = True
            if kind in {"decision", "agent_message"}:
                meta["execution_boundary"] = receipt.get("execution_boundary")
                meta["dirty"] = bool(receipt.get("active_activity") and self.store.read(db)["active"] is None)
                if receipt.get("selected", {}).get("action", {}).get("operation") == "wait":
                    meta["last_wait_basis"] = payload.get("decision_basis")
                else:
                    meta.pop("last_wait_basis", None)
                delay = self.config["idle_check_seconds"]
                if 'agent_wait_seconds' in receipt:
                    delay = receipt['agent_wait_seconds']
                plan = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","kind" AS "kind","body" AS "body" FROM life_evidence WHERE category=\'cognition\') AS life_cognition_artifacts WHERE id=?', (attempt+":plan",)).fetchone()
                if plan:
                    near = json.loads(plan[0])["items"][0]
                    planned = near["start_after_seconds"] + near["duration_seconds"]
                    delay = planned if receipt.get("selected", {}).get("action", {}).get("operation") == "wait" else max(delay, planned)
                # Receipt time survives commit-before-job-finish crashes and duplicate delivery.
                meta["next_decision"] = (utc(receipt["at"])+timedelta(seconds=delay)).isoformat()
                boundary = self.cog.agenda.boundary(utc(receipt["at"]))
                if boundary and boundary < utc(meta["next_decision"]):
                    meta["next_decision"] = boundary.isoformat()
            if kind in {"read", "world", "work"} and self.store.read(db)["active"] is None:
                meta["dirty"] = True
            if kind in {"read", "world", "work"}:
                boundary = meta.get("execution_boundary")
                state = self.store.read(db)
                if boundary and boundary["scope"] == "checkpoint":
                    current = state["activities"][boundary["activity_id"]]
                    if current["progress"] > boundary["progress"] or current["status"] in {"failed", "completed"}:
                        from .fine_plan import continuing_budget
                        continuing = continuing_budget(self.cog, db, state)
                        if not continuing: meta["dirty"] = True
                        meta["execution_boundary"] = None
                        self._record(db, "plan_checkpoint_requires_reassessment", {
                            "decision_id": boundary["decision_id"], "actual_result_job": job_id,
                            "activity_id": current["id"], "progress": current["progress"],
                            "rule": "continue saved fine budget after absorbing actual observations" if continuing else
                                    "absorb actual observations before fresh model choice; never promote tentative suffix"})
            self._save(db, meta)
            self._record(db, kind, {"job": job_id, "attempt": attempt, "receipt": receipt,
                                   "state": self.store.read(db)})
        return "worked"

    def pump(self):
        require(self.session is not None, "open worker context first")
        from .companionship import reconcile
        reconcile(self.cog)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            meta = self._meta(db)
            elapsed = (self.clock.now()-utc(meta["last_seen"])).total_seconds()
            require(elapsed >= 0, "clock moved backwards")
            if elapsed > self.p.config["max_gap_seconds"]:
                self._recover(db, meta, "worker clock jump/stall; no backfill")
            meta["last_seen"] = self.clock.now().isoformat()
            self._save(db, meta)
            jobs = db.execute("""SELECT j.* FROM life_scheduler_jobs j WHERE j.status!='done'
                AND NOT EXISTS (SELECT 1 FROM life_scheduler_recoveries r WHERE r.blocked_job_id=j.id)
                ORDER BY j.rowid LIMIT 1""").fetchone()
        from .skill_housework import tick_machines
        tick_machines(self.cog)
        from .outing_content import tick as outing_content_tick
        outing_content_tick(self.cog)
        from .weread_library import tick as weread_library_tick
        weread_library_tick(self.cog)
        from .book_library import tick as book_library_tick
        book_library_tick(self.cog)
        from .media_recommendations import tick as media_tick
        media_tick(self.cog)
        from .household_followups import refresh as refresh_household_followups
        refresh_household_followups(self.cog)
        if self.chat.start_pending_sleep_if_ready():
            return "sleep_started_after_bedtime_routine"
        if self.chat.start_fallback_sleep_if_ready():
            return "sleep_started_by_quiet_night_fallback"
        state = self.p.snapshot()
        if state['sleep']['status'] == 'sleeping' and (not jobs or jobs[1] not in {'message','failure','interrupt'}):
            return self._advance_sleep(state)
        if state["sleep"]["status"] == "awake":
            from .skill_dining import enabled as meal_enabled
            if meal_enabled(self.cog) and not getattr(self,'_meal_places_installed',False):
                from .meal_places import install
                self._meal_places_installed=install(self.cog)
            self.cog.agenda.ensure()
            from .coarse_locations import advance
            if advance(self.cog): return "coarse_state_entered"
            if getattr(self.cog, 'resource_root', None) and (not jobs or (jobs[1]=='decision' and jobs[3]=='pending')):
                next_resource_sync = getattr(self, '_next_resource_sync', None)
                if next_resource_sync is None or self.clock.now() >= next_resource_sync:
                    from .resource_library import sync
                    sync(self.cog, self.cog.resource_root)
                    self._next_resource_sync = self.clock.now()+timedelta(minutes=5)
                from .fine_plan import prepare
                from .fine_plan import pause_expired
                if pause_expired(self.cog): return 'fine_activity_paused'
                if self.agent is None and prepare(self.cog): return 'fine_agenda_prepared'
            agenda_basis = self._agenda_basis()
            if agenda_basis:
                with self.store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    agenda_meta = self._meta(db)
                    if agenda_meta.get("agenda_basis") != agenda_basis:
                        agenda_meta.update(agenda_basis=agenda_basis, dirty=True,
                                           next_decision=self.clock.now().isoformat())
                        self._save(db, agenda_meta)
            if self.p.config.get("mode") == "local_single_user" and not (jobs and jobs[3] == "running"):
                if self.agent is not None:
                    message_id = self.agent.pending_message()
                    if message_id:
                        # A delivered reply can reopen a completed user-message
                        # review. Give each reply revision its own durable job.
                        with self.store.connect() as db:
                            request_row = db.execute('SELECT request FROM life_received_messages WHERE id=?', (message_id,)).fetchone()
                        reply_evidence = json.loads(request_row[0]).get('assistant_replies', []) if request_row else []
                        review_key = message_id + (':reply:' + str(reply_evidence[-1]['id']) if reply_evidence else '')
                        job_id = self._job('agent_message', review_key, {'message_id': message_id})
                        with self.store.connect() as db:
                            job = db.execute('SELECT * FROM life_scheduler_jobs WHERE id=?', (job_id,)).fetchone()
                        if job[3] != 'done': return self._run_job(job)
                else:
                    from .coarse_plan_updates import process_pending
                    if process_pending(self.cog.agenda):
                        return "agenda_reviewed"
        if jobs and jobs[3] in {"running", "blocked"}:
            return self._run_job(jobs)
        from .household_followups import schedule_ready as schedule_household_followups
        if schedule_household_followups(self.cog):
            with self.store.connect() as db:
                meta=self._meta(db)
                meta.update(dirty=True,next_decision=self.clock.now().isoformat())
                self._save(db,meta)
            return 'household_followup_scheduled'
        if self._refresh_daily_routines():
            return "routine_materialized"
        from .coarse_plan_execution import pause_mismatch
        if pause_mismatch(self.cog):
            with self.store.connect() as db:
                meta = self._meta(db)
                meta.update(dirty=True, next_decision=self.clock.now().isoformat())
                self._save(db, meta)
            return 'coarse_activity_paused'
        from .coarse_plan_execution import enter_current
        if enter_current(self.cog):
            return 'coarse_state_entered'
        if jobs:
            return self._run_job(jobs)
        with self.store.connect() as db:
            item = db.execute("SELECT id,body FROM life_scheduler_inbox WHERE status='pending' AND due_at<=? ORDER BY due_at,rowid LIMIT 1",
                              (self.clock.now().isoformat(),)).fetchone()
        if item:
            body = json.loads(item[1])
            if body["type"] == "message":
                self._job("message", item[0], {"id": item[0], "message": body["message"]})
            else:
                state = self.p.snapshot()
                activity_id = body.get("activity_id") or state["active"]
                if not activity_id:
                    with self.store.connect() as db:
                        db.execute("UPDATE life_scheduler_inbox SET status='not_applicable' WHERE id=?", (item[0],))
                        self._record(db, "fixture_failure_not_applicable", {"input": item[0], "reason": "no active activity; do not fabricate a failure"})
                    return "worked"
                self._job(body["type"], item[0], {"id": item[0], "revision": state["revision"], "activity_id": activity_id,
                                             "reason": "explicit_test_fixture: " + body["reason"]})
            return "queued"
        state = self.p.snapshot()
        if state["sleep"]["status"] == "sleeping":
            episode = self.chat._episode(state)
            due = utc(episode["settled_until"]) + timedelta(seconds=self.config["sleep_checkpoint_seconds"])
            if episode["natural_wake_at"]:
                due = min(due, utc(episode["natural_wake_at"]))
            if self.clock.now() >= due:
                key = episode["id"] + ":" + episode["settled_until"]
                self._job("sleep", key, {"id": "p4:"+digest(key)[:24]})
                return "queued"
            return "idle_sleep"
        # Every committed outcome, including final natural wake, is absorbed first.
        self.cog.ingest()
        with self.store.connect() as db:
            pending = [r[0] for r in db.execute("SELECT id FROM life_observations WHERE processed=0 ORDER BY rowid")]
        if pending:
            self._job("sync", pending, {})
            return "queued"
        if state["sleep"]["status"] == "recovery_required":
            return "sleep_continuity_unconfigured"
        with self.store.connect() as db:
            meta = self._meta(db)
        due_commitments = [c["id"] for c in state["commitments"] if c["status"] == "confirmed"
                           and utc(c["due_at"]) <= self.clock.now() and c["id"] not in meta["seen_commitments"]]
        if due_commitments:
            with self.store.connect() as db:
                meta["seen_commitments"] += due_commitments
                meta["dirty"] = True
                self._save(db, meta)
        from .skill_reading import heartbeat
        from .skill_movie import heartbeat as movie_heartbeat
        from .skill_dining import heartbeat as meal_heartbeat
        from .skill_personal_care import heartbeat as care_heartbeat
        from .skill_housework import heartbeat as housework_heartbeat
        from .skill_exercise import heartbeat as exercise_heartbeat
        from .skill_television import heartbeat as television_heartbeat
        from .skill_rest import heartbeat as rest_heartbeat
        from .skill_outing import heartbeat as outing_heartbeat
        from .skill_work import heartbeat as work_heartbeat
        timed_activity = work_heartbeat(self.cog) or outing_heartbeat(self.cog) or rest_heartbeat(self.cog) or television_heartbeat(self.cog) or exercise_heartbeat(self.cog) or heartbeat(self.cog) or movie_heartbeat(self.cog) or meal_heartbeat(self.cog) or care_heartbeat(self.cog) or housework_heartbeat(self.cog)
        if timed_activity:
            from .quote_notebook import tick as quote_tick
            quote_tick(self.cog)
            if not meta['dirty']:
                if (state['activities'].get(state.get('active')) or {}).get('work_mode'): return 'daily_work'
                if (state['activities'].get(state.get('active')) or {}).get('outing_mode'): return 'outing'
                if (state['activities'].get(state.get('active')) or {}).get('rest_mode'): return 'resting'
                if (state['activities'].get(state.get('active')) or {}).get('television_mode'): return 'television_on'
                if (state['activities'].get(state.get('active')) or {}).get('exercise_mode'): return 'simulated_exercise'
                if (state['activities'].get(state.get('active')) or {}).get('housework_mode'): return 'simulated_housework'
                if (state['activities'].get(state.get('active')) or {}).get('care_mode'): return 'simulated_care'
                if (state['activities'].get(state.get('active')) or {}).get('meal_mode'):
                    return 'simulated_meal'
                return 'simulated_reading' if (state['activities'].get(state.get('active')) or {}).get('kind') == 'reading' else 'simulated_viewing'
            state = self.p.snapshot()
        if not state.get('active') and getattr(self.cog, 'resource_root', None):
            from .movie_reviews import process_one
            if process_one(self.cog):
                return 'movie_review_processed'
        # A fine block may end exactly at a due checkpoint. Settle only that
        # earned result before selecting a new activity; pause_expired already
        # rejects cancelled parents and checkpoints outside the budget.
        if state['active'] and getattr(self.cog,'resource_root',None):
            a=state['activities'][state['active']]
            with self.store.connect() as db:
                budget=db.execute('SELECT end_at FROM life_fine_execution WHERE activity_id=?',(a['id'],)).fetchone()
            if budget and a.get('next_due_at') and utc(a['next_due_at'])<=min(self.clock.now(),utc(budget[0])):
                kind={'reading':'read','work':'work'}.get(a['kind'],'world')
                self._job(kind,[a['id'],a['revision'],a['progress']],{})
                return 'queued'
        if meta["dirty"] or ((state["active"] is None or self.agent is not None)
                             and self.clock.now() >= utc(meta["next_decision"])):
            basis = self._decision_basis(state)
            if self.agent is None and not meta["dirty"] and meta.get("last_wait_basis") == basis:
                with self.store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    current = self._meta(db)
                    # Recheck the scheduling fields under the writer lock.  A
                    # concurrent host signal must win and force a fresh decision.
                    if (not current["dirty"] and current.get("last_wait_basis") == basis
                            and self.clock.now() >= utc(current["next_decision"])):
                        current["next_decision"] = (self.clock.now() + timedelta(
                            seconds=self.config["idle_check_seconds"])).isoformat()
                        boundary = self.cog.agenda.boundary()
                        if boundary and boundary < utc(current["next_decision"]):
                            current["next_decision"] = boundary.isoformat()
                        self._save(db, current)
                        self._record(db, "unchanged_wait_checkpoint", {
                            "decision_basis": basis,
                            "effect": "no model call and no life event; next deterministic check scheduled",
                            "state_revision": state["revision"]})
                        return "idle_unchanged"
            self._job("decision", [state["revision"], meta["next_decision"], basis],
                      {"decision_basis": basis})
            return "queued"
        if state["active"]:
            a = state["activities"][state["active"]]
            if self.clock.now() >= utc(a["next_due_at"]):
                if a["kind"] == "work":
                    self._job("work", [a["id"], a["revision"], a["progress"]], {})
                    return "queued"
                if a["kind"] != "reading":
                    if not self.p.config.get("household_world"):
                        return "world_executor_unconfigured"
                    self._job("world", [a["id"], a["revision"], a["progress"]], {})
                    return "queued"
                self._job("read", [a["id"], a["revision"], a["progress"]], {})
                return "queued"
        return "idle"

    def run(self, seconds, *, advance=None, poll=None, frozen_test_resume=False, recovery=None, until=None):
        """Continuous worker. Test runner supplies time adapter, never calls demo steps."""
        require(seconds > 0, "positive duration required")
        require((advance is not None) == isinstance(self.clock, TestClock), "clock adapter mismatch")
        start_wall, start_clock = time.monotonic(), self.clock.now()
        stop = start_clock + timedelta(seconds=seconds)
        status, polls = "starting", 0
        with self.worker(frozen_test_resume=frozen_test_resume):
            if recovery:
                self.recover_blocked(**recovery)
            while (self.clock.now() < stop if advance else time.monotonic()-start_wall < seconds):
                status = self.pump(); polls += 1
                if poll:
                    poll(status, self)
                if until and until(self):
                    status = "acceptance_checkpoint"
                    break
                if status in {"blocked", "world_executor_unconfigured","time_continuity_unconfigured"}:
                    break
                if status in {"queued", "worked"}:
                    continue
                if advance:
                    advance(min(self._test_delay(), (stop-self.clock.now()).total_seconds()))
                else:
                    time.sleep(self.config["poll_seconds"])
        record = {"status": status, "polls": polls, "wall_seconds": time.monotonic()-start_wall,
                  "world_start": start_clock.isoformat(), "world_end": self.clock.now().isoformat(),
                  "requested_seconds": seconds, "clock": type(self.clock).__name__,
                  "inflight_call_may_extend_duration": True}
        with self.store.connect() as db:
            self._record(db, "run_summary", record)
        return record

    def _test_delay(self):
        """Discrete-event test clock only: visit every deadline, never skip a result.

        Bound each jump by the continuity limit; real time always uses actual sleep.
        This avoids thousands of empty disk heartbeats in the full-day fixture.
        """
        now = self.clock.now()
        deadlines = []
        with self.store.connect() as db:
            deadlines += [utc(r[0]) for r in db.execute("SELECT due_at FROM life_scheduler_inbox WHERE status='pending'")]
            deadlines += [utc(r[0]) for r in db.execute("SELECT retry_at FROM life_scheduler_jobs WHERE status='pending' AND retry_at IS NOT NULL")]
            meta = self._meta(db)
        state = self.p.snapshot()
        if state["sleep"]["status"] == "sleeping":
            episode = self.chat._episode(state)
            deadlines.append(utc(episode["settled_until"])+timedelta(seconds=self.config["sleep_checkpoint_seconds"]))
            if episode["natural_wake_at"]:
                deadlines.append(utc(episode["natural_wake_at"]))
        elif state["active"]:
            deadlines.append(utc(state["activities"][state["active"]]["next_due_at"]))
            if self.agent is not None:
                deadlines.append(utc(meta["next_decision"]))
        elif state["sleep"]["status"] == "awake":
            deadlines.append(utc(meta["next_decision"]))
        deadlines += [utc(c["due_at"]) for c in state["commitments"] if c["status"] == "confirmed"
                      and c["id"] not in meta["seen_commitments"]]
        future = [(due-now).total_seconds() for due in deadlines if due > now]
        return min([self.p.config["max_gap_seconds"], *future])

    def inspect(self):
        from .storage_layout import audit_cursor
        with self.store.connect() as db:
            db.execute("BEGIN")
            audit = {"state": self.store.read(db), "config": self.chat.config}
            for table in ("events", "reading_records", "results", "result_controls", "result_reviews", "result_attempts",
                          "life_observations", "life_memories", "life_observation_updates", "life_model_calls", "life_cognition_runs", "life_memory_retrievals",
                          "life_cognition_artifacts", "life_received_messages", "life_sleep_ticks", "life_interaction_replies", "life_message_archive",
                          "life_scheduler_state", "life_scheduler_jobs", "life_scheduler_attempts", "life_scheduler_inbox", "life_scheduler_logs", "life_scheduler_recoveries", "life_scheduler_signals",
                          "life_model_transport_attempts"):
                cursor = audit_cursor(db, table)
                audit[table] = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
            if db.execute("SELECT 1 FROM life_evidence WHERE category='world_check' LIMIT 1").fetchone():
                audit["home_world_checks"] = [{"id": r[0], "body": r[1]} for r in db.execute('SELECT id,body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_evidence WHERE category=\'world_check\') AS home_world_checks ORDER BY rowid')]
        from .movement_evidence import summary_view
        audit["effective_observation_summaries"] = summary_view(audit)
        return audit
