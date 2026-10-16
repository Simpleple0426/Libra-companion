"""P1 activity state machine; P2 cognition lives in its separate coordinator.

All transitions and world effects are project engineering adaptations (A).
Validated results advance work; structure-only reading uses persisted simulated time.
P2 model reading additionally requires a recorded call and matching checkpoint.
"""
from datetime import timedelta
from copy import deepcopy
import json

from .clock import utc
from .config import canonical, digest
from .store import Conflict, Store


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Prototype:
    def __init__(self, run_id, config, clock, root=None):
        self.store = Store(run_id, config, clock, root=root)
        from .world_extensions import effective
        self.config = effective(self.store)
        from .resource_library import effective as resources_effective
        self.config = resources_effective(self.store, self.config)
        self.clock = clock

    def snapshot(self):
        return self.store.snapshot()

    def due(self):
        """Read-only signal, including overdue checkpoints after restart."""
        state = self.snapshot()
        return [a["id"] for a in state["activities"].values()
                if a["status"] == "running" and utc(a["next_due_at"]) <= self.clock.now()]

    def proposal(self, proposal_id, kind, body):
        require(kind in {"plan", "forecast"}, "proposal kind required")
        require(isinstance(body, dict) and bool(proposal_id), "proposal id/body required")
        value = canonical({"source": "test_fixture", "body": body})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute('SELECT kind, body FROM (SELECT rowid,"id" AS "id","kind" AS "kind","body" AS "body" FROM life_evidence WHERE category=\'proposal\') AS proposals WHERE id=?', (proposal_id,)).fetchone()
            if old:
                require(old == (kind, value), "proposal id reused with different content")
            else:
                db.execute("INSERT INTO life_evidence(category,id,kind,body) VALUES('proposal',?,?,?)", (proposal_id, kind, value))

    def command(self, event_id, expected_revision, operation, **payload):
        """Explicit start/interrupt/resume/fail/recover; retries return original receipt."""
        request = {"operation": operation, "payload": payload, "expected_revision": expected_revision}
        return self._commit(event_id, request, None)

    def stage_result(self, result_id, expected_revision, activity_id, evidence, occurred_at=None):
        """Durably retain a controlled result before settlement, including its input revision."""
        require(isinstance(result_id, str) and bool(result_id), "result id required")
        require(isinstance(evidence, dict) and evidence.get("source") in {"controlled_test", "model_reading", "model_work", "simulated_world"},
                "only controlled_test, audited model_reading/model_work or verified simulated_world evidence is accepted")
        require(type(expected_revision) is int, "integer revision required")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            model_checkpoint = None
            if evidence["source"] == "model_work":
                from .work_artifacts import provenance
                work_context = provenance(self, db, evidence)
                require(work_context["state"]["revision"] == expected_revision and work_context["activity_id"] == activity_id, "work input version/activity mismatch")
            if evidence["source"] == "simulated_world":
                from .home_world import verify
                checked = verify(self, db, evidence)
                require(checked["snapshot"]["revision"] == expected_revision and checked["activity_id"] == activity_id,
                        "world input version/activity mismatch")
            if evidence["source"] == "model_reading":
                model_checkpoint = self._reading_call(db, evidence)
                require(model_checkpoint["checkpoint"]["revision"] == expected_revision
                        and model_checkpoint["activity_id"] == activity_id, "reading input version/activity mismatch")
            old = db.execute("SELECT body FROM results WHERE id=?", (result_id,)).fetchone()
            # Omitted time on retry means the originally persisted occurrence time.
            time = occurred_at or (json.loads(old[0])["occurred_at"] if old else self.clock.now().isoformat())
            value = {"expected_revision": expected_revision, "activity_id": activity_id,
                     "evidence": evidence, "occurred_at": utc(time).isoformat()}
            require(utc(time) <= self.clock.now(), "future result")
            if old:
                require(old[0] == canonical(value), "result id reused with different content")
            else:
                db.execute("INSERT INTO results VALUES(?,?,NULL)", (result_id, canonical(value)))
                context = {"snapshot": self.store.read(db), "source_revision": expected_revision,
                           "staged_at": self.clock.now().isoformat()}
                if model_checkpoint:
                    context["snapshot"] = model_checkpoint["checkpoint"]
                db.execute("INSERT INTO result_controls VALUES(?,?,NULL,'pending',?,'standard')",
                           (result_id, result_id, canonical(context)))
        return result_id

    def settle(self, result_id):
        require(isinstance(result_id, str) and bool(result_id), "result id required")
        # Record rejected attempts inside the same writer lock as the version check.
        # The savepoint rolls back ALL world effects before retaining the audit.
        error = None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            revision = self.store.read(db)["revision"]
            db.execute("SAVEPOINT settlement")
            try:
                receipt = self._commit_locked(db, "result:" + result_id, None, result_id)
            except ValueError as exc:
                db.execute("ROLLBACK TO settlement")
                error = exc
                if db.execute("SELECT 1 FROM results WHERE id=?", (result_id,)).fetchone():
                    db.execute("INSERT OR IGNORE INTO result_attempts VALUES(?,?,?,?)",
                               (result_id, revision, str(exc), self.clock.now().isoformat()))
            finally:
                db.execute("RELEASE settlement")
        if error is not None:
            raise error
        return receipt

    def review_result(self, review_id, result_id, expected_revision, action, reason, *,
                      replacement_id=None, evidence=None, occurred_at=None):
        """Audit an explicit reevaluate/void/replace decision; never settle implicitly.

        An accepted reevaluation supersedes its immutable source with a new result
        tied to the checked revision. Rejected decisions are durable and idempotent.
        Replacement at the original occurrence time uses the captured checkpoint;
        a new occurrence time requires fresh evidence valid against the live state.
        """
        require(isinstance(review_id, str) and bool(review_id), "review id required")
        require(isinstance(result_id, str) and bool(result_id), "result id required")
        require(type(expected_revision) is int, "integer revision required")
        require(action in {"reevaluate", "void", "replace"}, "invalid review action")
        require(isinstance(reason, str) and bool(reason.strip()), "review reason required")
        if action == "void":
            require(replacement_id is None and evidence is None and occurred_at is None,
                    "void cannot supply a replacement")
        else:
            require(isinstance(replacement_id, str) and bool(replacement_id)
                    and replacement_id != result_id, "new replacement id required")
            if action == "reevaluate":
                require(evidence is None and occurred_at is None, "reevaluate cannot edit source evidence/time")
            else:
                require(isinstance(evidence, dict) and evidence.get("source") == "controlled_test"
                        and occurred_at is not None, "replace requires explicit controlled evidence and time")
        request = {"result_id": result_id, "expected_revision": expected_revision, "action": action,
                   "reason": reason, "replacement_id": replacement_id, "evidence": evidence,
                   "occurred_at": utc(occurred_at).isoformat() if occurred_at is not None else None}
        encoded = canonical(request)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute('SELECT request, receipt FROM (SELECT rowid,"id" AS "id","request" AS "request","receipt" AS "receipt" FROM life_receipts WHERE category=\'result_review\') AS result_reviews WHERE id=?', (review_id,)).fetchone()
            if old:
                require(old[0] == encoded, "review id reused with different content")
                return json.loads(old[1])
            state = self.store.read(db)
            now = self.clock.now()
            receipt = {"review_id": review_id, "result_id": result_id, "action": action,
                       "checked_revision": state["revision"], "recorded_at": now.isoformat(),
                       "status": "rejected"}
            db.execute("SAVEPOINT review_decision")
            try:
                row = db.execute("SELECT body FROM results WHERE id=?", (result_id,)).fetchone()
                require(row is not None, "missing staged result")
                control = self._control(db, result_id)
                require(control["status"] == "pending", "result is " + control["status"])
                if expected_revision != state["revision"]:
                    raise Conflict("stale snapshot during review")
                require(now >= utc(state["as_of"]), "backdated review")
                receipt["root_result_id"] = control["root_id"]
                if action == "void":
                    db.execute("UPDATE result_controls SET status='void' WHERE result_id=?", (result_id,))
                else:
                    require(not db.execute("SELECT 1 FROM results WHERE id=?", (replacement_id,)).fetchone(),
                            "replacement id already exists")
                    source = json.loads(row[0])
                    candidate = {**source, "expected_revision": expected_revision}
                    context = control["context"]
                    mode = "deferred"
                    if action == "replace":
                        candidate.update(evidence=evidence, occurred_at=request["occurred_at"])
                        if candidate["occurred_at"] != source["occurred_at"]:
                            require(utc(candidate["occurred_at"]) > utc(source["occurred_at"]),
                                    "replacement cannot move occurrence backwards")
                            mode = "standard"
                            context = {"snapshot": state, "source_revision": expected_revision,
                                       "staged_at": now.isoformat()}
                    # Exercise the exact settlement checks, then discard their writes.
                    db.execute("SAVEPOINT review_validation")
                    try:
                        self._apply_result(deepcopy(state), candidate, replacement_id, mode, context, now, db)
                    finally:
                        db.execute("ROLLBACK TO review_validation")
                        db.execute("RELEASE review_validation")
                    db.execute("INSERT INTO results VALUES(?,?,NULL)", (replacement_id, canonical(candidate)))
                    db.execute("INSERT INTO result_controls VALUES(?,?,?,'pending',?,?)",
                               (replacement_id, control["root_id"], result_id,
                                canonical(context) if context else None, mode))
                    db.execute("UPDATE result_controls SET status='superseded' WHERE result_id=?", (result_id,))
                    receipt.update(replacement_id=replacement_id, mode=mode)
                receipt["status"] = "accepted"
            except ValueError as exc:
                db.execute("ROLLBACK TO review_decision")
                receipt["error"] = str(exc)
            finally:
                db.execute("RELEASE review_decision")
            db.execute("INSERT INTO life_receipts(category,id,request,receipt) VALUES('result_review',?,?,?)", (review_id, encoded, canonical(receipt)))
            return receipt

    @staticmethod
    def _control(db, result_id):
        row = db.execute("SELECT root_id, parent_id, status, context, mode FROM result_controls WHERE result_id=?",
                         (result_id,)).fetchone()
        require(row is not None, "missing result control")
        return {"root_id": row[0], "parent_id": row[1], "status": row[2],
                "context": json.loads(row[3]) if row[3] else None, "mode": row[4]}

    def _commit(self, event_id, request, result_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._commit_locked(db, event_id, request, result_id)

    def _commit_locked(self, db, event_id, request, result_id):
        require(isinstance(event_id, str) and bool(event_id), "event id required")
        require(result_id is not None or not event_id.startswith("result:"), "reserved event namespace")
        result = None
        if result_id is not None:
            row = db.execute("SELECT body, receipt FROM results WHERE id=?", (result_id,)).fetchone()
            require(row is not None, "missing staged result")
            result = json.loads(row[0])
            if row[1]:
                return json.loads(row[1])
            control = self._control(db, result_id)
            require(control["status"] == "pending", "result is " + control["status"])
            result["root_result_id"] = control["root_id"]
            request = {"operation": "result", **result, "settlement_mode": control["mode"]}
        encoded = canonical(request)
        old = db.execute("SELECT request, receipt FROM (SELECT rowid,id,request,receipt FROM life_receipts WHERE category='event_control') WHERE id=?", (event_id,)).fetchone()
        if old:
            require(old[0] == encoded, "event id reused with different content")
            return json.loads(old[1])
        state = self.store.read(db)
        if request["expected_revision"] != state["revision"]:
            raise Conflict("stale snapshot; retain pending result and re-evaluate explicitly")
        now = self.clock.now()
        previous_active = state['activities'].get(state.get('active'))
        at = utc(result["occurred_at"]) if result else now
        if result:
            self._apply_result(state, result, result_id, control["mode"], control["context"], now, db)
        else:
            require(utc(state["as_of"]) <= at <= now, "backdated or future event")
            self._transition(state, request["operation"], request["payload"], at)
        state["revision"] += 1
        applied_at = now if result and control["mode"] == "deferred" else at
        state["as_of"] = applied_at.isoformat()
        receipt = {"event_id": event_id, "revision": state["revision"],
                   "occurred_at": at.isoformat(), "recorded_at": now.isoformat(),
                   "applied_at": applied_at.isoformat(),
                       "source": result["evidence"]["source"] if result else "prototype_control"}
        if previous_active and previous_active.get('reading_mode') == 'structure_simulation' and request['operation'] == 'recover':
            receipt['reading_session_ended'] = previous_active['id']
        if previous_active and previous_active.get('viewing_mode') == 'active_time_simulation' and request['operation'] == 'recover':
            receipt['viewing_session_ended'] = previous_active['id']
        if previous_active and previous_active.get('meal_mode') and request['operation']=='recover':
            receipt['meal_session_ended'] = previous_active['id']
        if previous_active and previous_active.get('care_mode') and request['operation']=='recover':
            receipt['care_session_ended']=previous_active['id']
        if previous_active and previous_active.get('housework_mode') and request['operation']=='recover':
            receipt['housework_session_ended']=previous_active['id']
        if previous_active and previous_active.get('work_mode') and request['operation']=='recover':
            receipt['work_session_ended']=previous_active['id']
        if previous_active and previous_active.get('exercise_mode') and request['operation']=='recover':
            receipt['exercise_session_ended']=previous_active['id']
        if previous_active and previous_active.get('television_mode') and request['operation']=='recover':
            receipt['television_session_ended']=previous_active['id']
        if previous_active and previous_active.get('rest_mode') and request['operation']=='recover':
            receipt['rest_session_ended']=previous_active['id']
        if previous_active and previous_active.get('outing_mode') and request['operation']=='recover':
            receipt['outing_session_ended']=previous_active['id']
        care_activity=state['activities'].get(request.get('payload',{}).get('activity_id'),{})
        if care_activity.get('care_mode') and care_activity['status']=='completed' and request['operation']=='interrupt':
            receipt['care_completed']={'actor':self.config['persona']['id'],'operation':'care_result',
                'activity_id':care_activity['id'],'kind':care_activity['kind'],'target':care_activity['target'],
                'actual_result':{'source':'personal_care_simulation','routine':care_activity['care_routine'],
                    'steps':care_activity['care_steps'],'seconds':care_activity['progress']}}
        meal_activity = state['activities'].get(request.get('payload',{}).get('activity_id'),{})
        if meal_activity.get('meal_mode') and meal_activity['kind']=='eating' and meal_activity['status']=='completed' and request['operation']=='interrupt':
            receipt['meal_completed'] = {'actor':self.config['persona']['id'],'operation':'meal_result',
                'activity_id':meal_activity['id'],'kind':'eating','target':meal_activity['target'],
                'actual_result':{'source':'timed_meal_simulation','seconds':meal_activity['progress'],
                                 'portion':1,'dishes':meal_activity['dishes']}}
        if result:
            receipt.update(root_result_id=control["root_id"], parent_result_id=control["parent_id"])
        db.execute("UPDATE life_state SET body=?  WHERE name='current' AND ( id=1)", (canonical(state),))
        from .event_store import append
        append(db, event_id, request, receipt, state, self.config)
        if result:
            db.execute("UPDATE results SET receipt=? WHERE id=?", (canonical(receipt), result_id))
            db.execute("UPDATE result_controls SET status='settled' WHERE result_id=?", (result_id,))
        return receipt

    def _effect_inputs(self, state, activity_id):
        """Only control transitions may differ during late settlement.

        Compare all activity fields except explicit interrupt/resume controls,
        plus every shared input consumed or overwritten by this result kind.
        New unknown activity fields therefore fail closed instead of being ignored.
        """
        require(activity_id in state["activities"], "unknown activity")
        a = state["activities"][activity_id]
        controls = {"status", "revision", "next_due_at", "last_progress_at", "interrupted_at",
                    "resumed_at", "reason", "interruption"}
        inputs = {"activity": {key: value for key, value in a.items() if key not in controls},
                  "place": state["place"]}
        if a['kind']=='watching':
            inputs['viewing']=state.get('viewing',{}).get(a['target'],0)
        elif a.get('work_mode'):
            inputs['work_step']=state['work_steps'][a['target']]
        elif a["kind"] == "work":
            inputs["work_item"] = state["work_items"][a["target"]]
        elif a["kind"] == "reading":
            inputs["reading"] = state["reading"].get(a["progress_key"], 0)
        elif a["kind"] == "cooking":
            recipe = self.config["recipes"][a["target"]]
            inputs["inventory"] = {key: state["inventory"].get(key, 0) for key in recipe["ingredients"]}
            inputs["meal"] = state["meals"].get(activity_id)
        elif a["kind"] in {"moving", "serving"}:
            inputs["meals"] = state["meals"]
        elif a["kind"] == "showering":
            inputs["daily_routines"] = self.config.get("daily_routines")
        else:
            inputs["meal"] = state["meals"].get(a["target"])
            if not state.get("cognition_enabled"):
                inputs["test_hunger"] = state["test_hunger"]
        return inputs

    def _apply_result(self, state, result, result_id, mode, context, now, db):
        at = utc(result["occurred_at"])
        if mode == "standard":
            require(utc(state["as_of"]) <= at <= now, "backdated or future event")
            self._result(state, result, result_id, at, db)
            return
        require(context is not None, "no captured checkpoint; void or replace with fresh evidence")
        baseline = context["snapshot"]
        require(baseline["revision"] == context["source_revision"], "source staged against stale checkpoint")
        require(utc(baseline["as_of"]) <= at <= now and utc(state["as_of"]) <= now,
                "backdated or future event")
        activity_id = result["activity_id"]
        require(activity_id in state["activities"], "unknown activity")
        current = deepcopy(state["activities"][activity_id])
        require(current["status"] in {"running", "interrupted"}, "cannot reconcile terminal activity")
        require(self._effect_inputs(state, activity_id) == self._effect_inputs(baseline, activity_id),
                "settlement inputs changed; void or replace after re-evaluation")
        # Use the original running checkpoint, never the interruption/resume time,
        # for the original evidence. Preserve unrelated activities and current control.
        require(baseline["active"] == activity_id, "source activity was not active")
        active = state["active"]
        state["activities"][activity_id] = deepcopy(baseline["activities"][activity_id])
        state["active"] = activity_id
        self._result(state, result, result_id, at, db)
        updated = state["activities"][activity_id]
        updated["revision"] = current["revision"] + 1
        state["active"] = active
        for key in ("interrupted_at", "resumed_at", "reason", "interruption"):
            if key in current:
                updated[key] = current[key]
        if updated["status"] == "completed":
            if active == activity_id:
                state["active"] = None
        else:
            updated["status"] = current["status"]
            updated["last_progress_at"] = max(utc(current["last_progress_at"]), at).isoformat()
            updated["next_due_at"] = (max(utc(current["next_due_at"]), utc(updated["next_due_at"])).isoformat()
                                      if current["status"] == "running" else None)

    def _due_at(self, at, activity=None):
        from .world_extensions import duration
        return (at + timedelta(seconds=duration(self.config, activity))).isoformat()

    def _transition(self, s, operation, p, at):
        if operation in {"start", "resume"}:
            require(s.get("sleep", {}).get("status") != "sleeping", "cannot act while P3 sleeping")
        allowed = {
            "start": {"activity_id", "kind", "target"},
            "interrupt": {"activity_id", "reason"}, "resume": {"activity_id"},
            "fail": {"activity_id", "reason"}, "recover": {"reason"},
            "world_tool": {"tool", "available", "source"},
        }
        require(operation in allowed and set(p) == allowed[operation], "invalid command fields")
        if operation == "world_tool":
            require(self.config.get("household_world", {}).get("source") == "test_fixture"
                    and p["source"] == "test_fixture" and type(p["available"]) is bool
                    and p["tool"] in self.config["objects"], "invalid isolated world fault")
            tools = set(s.get("available_tools", self.config["initial"]["available_tools"]))
            if p["available"]: tools.add(p["tool"])
            else: tools.discard(p["tool"])
            s["available_tools"] = sorted(tools)
            return
        if operation == "recover":
            require(bool(p["reason"]), "recovery reason required")
            s["gaps"].append({"from": s["as_of"], "to": at.isoformat(), "reason": p["reason"],
                              "policy": "prototype_no_backfill"})
            if s["active"]:
                a = s["activities"][s["active"]]
                from .skill_reading import settle
                settle(self.config, s, a, at, recovering=True)
                from .skill_movie import settle as settle_movie
                settle_movie(self.config, s, a, at, recovering=True)
                from .skill_dining import settle as settle_meal
                settle_meal(self.config,s,a,at,recovering=True)
                from .skill_personal_care import settle as settle_care
                settle_care(self.config,s,a,at,recovering=True)
                from .skill_housework import settle as settle_housework
                settle_housework(self.config,s,a,at,recovering=True)
                from .skill_work import settle as settle_work
                settle_work(self.config,s,a,at,recovering=True)
                from .skill_exercise import settle as settle_exercise
                settle_exercise(self.config,s,a,at,recovering=True)
                resumable = a.get('kind') in {'reading', 'watching'}
                a.update(status="interrupted" if resumable else "failed", next_due_at=None,
                         interruption=("restart recovery; progress retained" if resumable else
                                       "restart recovery; ordinary activity closed without retained progress"),
                         interrupted_at=at.isoformat(), revision=a["revision"] + 1)
                from .skill_television import close as close_television
                close_television(s,a,at)
                from .skill_rest import close as close_rest
                close_rest(s,a,at)
                from .skill_outing import close as close_outing
                close_outing(s,a,at)
                s["active"] = None
            return
        activity_id = p["activity_id"]
        require(isinstance(activity_id, str) and bool(activity_id), "activity id required")
        if operation == "start":
            require(s["active"] is None and activity_id not in s["activities"], "activity already active/existing")
            kind, target = p["kind"], p["target"]
            require(self.config.get('mode') != 'local_single_user' or kind not in {'moving', 'serving'},
                    'independent movement removed; location is owned by coarse schedule')
            require(kind in {"reading", "cooking", "eating", "moving", "serving", "work", "showering", "exercising", "personal_care", "housework", "television", "rest", "outing", "watching"}, "unsupported P1 activity")
            a = {"id": activity_id, "kind": kind, "target": target, "status": "running",
                 "started_at": at.isoformat(), "last_progress_at": at.isoformat(),
                 "next_due_at": self._due_at(at), "progress": 0, "revision": 1, "place": s["place"]}
            if kind=='outing':
                from .skill_outing import begin as begin_outing
                begin_outing(self.config,s,a,at)
            elif kind=='rest':
                from .skill_rest import begin as begin_rest
                begin_rest(self.config,s,a,at)
            elif kind=='television':
                from .skill_television import begin as begin_television
                begin_television(self.config,s,a,at)
            elif kind=='exercising':
                from .skill_exercise import begin as begin_exercise
                begin_exercise(self.config,s,a,at)
            elif kind=='housework':
                require(target in s.get('housework_steps',{}),'housework plan required')
                from .skill_housework import begin as begin_housework
                begin_housework(self.config,s,a,at)
            elif kind in {'personal_care','showering'} and target in s.get('care_plans',{}):
                from .skill_personal_care import begin as begin_care
                begin_care(self.config,s,a,at)
            elif kind == 'personal_care':
                raise ValueError('care plan required')
            elif kind in {'cooking','eating'} and target in s.get('meal_plans',{}):
                from .skill_dining import begin as begin_meal
                begin_meal(self.config,s,a,at)
            elif kind == "watching":
                movie = self.config.get('movies', {}).get(target)
                require(movie and movie.get('available', True), 'movie is not available')
                require(s['place'] == movie['place'], 'movie place mismatch')
                require(not any(x['kind']=='watching' and x['target']==target and x['status'] in {'running','interrupted'} for x in s['activities'].values()), 'resume unfinished viewing')
                a['progress'] = s.get('viewing', {}).get(target, 0)
                if movie.get('viewing_mode') == 'active_time_simulation':
                    from .skill_movie import begin
                    begin(self.config, s, a, at)
            elif kind == 'work' and target in s.get('work_steps',{}):
                from .skill_work import begin as begin_work
                begin_work(self.config,s,a,at)
            elif kind == "work":
                require(target in self.config.get("work_items", {}), "unknown work item")
                task = self.config["work_items"][target]; job = s["work_items"][target]
                require(s["place"] == task["place"] and job["progress"] < 2, "work place/completion mismatch")
                require(not any(x["kind"] == "work" and x["target"] == target and x["status"] in {"running", "interrupted"} for x in s["activities"].values()), "resume unfinished work")
                a["progress"] = job["progress"]
                job["status"] = "in_progress"
            elif kind == "reading":
                require(target in self.config["books"], "missing book content")
                book = self.config["books"][target]
                require(book.get('available', True), 'book is no longer available')
                require(self.config["objects"][book["object"]]["parent"] == s["place"], "book not at current place")
                key = target + ":" + book["version"]
                from .skill_reading import simulated, length, begin
                a.update(content_version=book["version"], content_hash=digest(book.get('text', book.get('structure'))),
                         progress_key=key, progress=s["reading"].get(key, 0))
                require(a["progress"] < length(book), "book already completed")
                if simulated(book):
                    require(not any(x['kind'] == 'reading' and x['target'] == target
                                    and x['status'] in {'running', 'interrupted'} for x in s['activities'].values()),
                            'resume unfinished reading')
                    begin(self.config, s, a, at)
            elif kind == "cooking":
                require(target in self.config["recipes"], "unknown recipe")
                recipe = self.config["recipes"][target]
                require(self.config["objects"][recipe["tool"]]["parent"] == s["place"], "tool not at current place")
                self._resources(s, recipe)
                a["ingredients_consumed"] = False
            elif kind in {"moving", "serving"}:
                from .home_world import path
                dest = target
                if kind == "serving":
                    require(target in s["meals"] and s["meals"][target]["remaining"] > 0
                            and s["meals"][target]["place"] == s["place"], "no local food to carry")
                    require(not s['meals'][target].get('meal_skill') or s['meals'][target].get('ready'), 'meal not yet prepared')
                    dest = self.config.get("household_world", {}).get("dining_place")
                require(dest in self.config["places"] and dest != s["place"], "invalid movement destination")
                a["route"] = path(self.config, s["place"], dest)
                from .skill_exercise import departure
                departure(s,a,at)
                from .skill_work import departure as work_departure
                work_departure(s,a,at)
                s.pop("outing_visit",None)
            elif kind == "showering":
                rules = self.config.get("daily_routines", {}).get("shower", {})
                from .daily_obligations import local_day, target as routine_target
                require(target == routine_target(local_day(at).date().isoformat(), "shower"), "invalid shower obligation")
                require(s["place"] == rules.get("place"), "shower requires configured bathroom")
                require(not any(x["kind"] == "showering" and x["target"] == target and x["status"] == "completed"
                                for x in s["activities"].values()), "daily shower already completed")
                a["duration_seconds"] = rules["duration_seconds"]
            else:
                require(target in s["meals"] and s["meals"][target]["remaining"] > 0, "no prepared food")
                require(s["meals"][target]["place"] == s["place"], "food not at current place")
                if self.config.get("household_world"):
                    require(s["meals"][target].get("source") == "user_confirmed_general_meal"
                            or s["place"] == self.config["household_world"]["dining_place"],
                            "serving place required before eating")
            a["next_due_at"] = self._due_at(at, a)
            s["activities"][activity_id] = a
            s["active"] = activity_id
            return
        require(activity_id in s["activities"], "unknown activity")
        a = s["activities"][activity_id]
        if operation == "resume":
            require(self.config.get('mode') != 'local_single_user' or a['kind'] not in {'moving', 'serving'},
                    'independent movement removed; use coarse schedule')
            require(a["status"] == "interrupted" and s["active"] is None, "cannot resume")
            require(a["place"] == s["place"], "activity location changed")
            if a.get('work_mode'):
                from .skill_work import begin as begin_work
                begin_work(self.config,s,a,at)
            if a.get('exercise_mode'):
                from .skill_exercise import begin as begin_exercise
                begin_exercise(self.config,s,a,at)
            if a.get('housework_mode'):
                from .skill_housework import begin as begin_housework
                begin_housework(self.config,s,a,at)
            if a.get('care_mode'):
                from .skill_personal_care import begin as begin_care
                begin_care(self.config,s,a,at)
            if a.get('meal_mode'):
                from .skill_dining import begin as begin_meal
                begin_meal(self.config,s,a,at)
            if a['kind'] == 'watching' and self.config['movies'][a['target']].get('viewing_mode') == 'active_time_simulation':
                from .skill_movie import begin
                begin(self.config, s, a, at, resuming=True)
            if a.get('reading_mode') == 'structure_simulation':
                from .skill_reading import begin, length
                require(self.config['books'][a['target']].get('available', True), 'book no longer available')
                require(a['progress'] < length(self.config['books'][a['target']]), 'book already completed')
                a.pop('reading_deadline', None)
                begin(self.config, s, a, at)
            a.update(status="running", next_due_at=self._due_at(at, a), last_progress_at=at.isoformat(),
                     resumed_at=at.isoformat())
            s["active"] = activity_id
        else:
            require(a["status"] in {"running", "interrupted"}, "terminal activity")
            require(bool(p["reason"]), "reason required")
            if operation == "interrupt":
                require(a["status"] == "running", "already interrupted")
            from .skill_reading import settle, length
            settle(self.config, s, a, at)
            from .skill_movie import settle as settle_movie
            settle_movie(self.config, s, a, at)
            from .skill_dining import settle as settle_meal
            settle_meal(self.config,s,a,at)
            from .skill_personal_care import settle as settle_care
            settle_care(self.config,s,a,at)
            from .skill_housework import settle as settle_housework
            settle_housework(self.config,s,a,at)
            from .skill_work import settle as settle_work
            settle_work(self.config,s,a,at)
            from .skill_exercise import settle as settle_exercise, finish as finish_exercise
            settle_exercise(self.config,s,a,at)
            a.update(status="interrupted" if operation == "interrupt" else "failed",
                     next_due_at=None, reason=p["reason"])
            a["interrupted_at" if operation == "interrupt" else "failed_at"] = at.isoformat()
            if s["active"] == activity_id:
                s["active"] = None
            if a.get('reading_mode') == 'structure_simulation' and a['progress'] >= length(self.config['books'][a['target']]):
                a['status'] = 'completed'
            if a.get('viewing_mode') == 'active_time_simulation' and a['progress'] >= a['movie_duration_seconds']:
                a['status'] = 'completed'
            if (a.get('work_mode') or a.get('meal_mode') or a.get('care_mode') or a.get('housework_mode')) and a['progress']>=a['duration_seconds']:
                a['status'] = 'completed'
                a['completed_at'] = at.isoformat()
            from .skill_television import close as close_television
            close_television(s,a,at)
            from .skill_rest import close as close_rest
            close_rest(s,a,at)
            from .skill_outing import close as close_outing
            close_outing(s,a,at)
            if a.get('exercise_mode') in {'running','swimming','shooting'} and operation == 'interrupt' and at >= utc(s['exercise_sessions'][a['target']]['end_at']):
                finish_exercise(s,a,at)
        a["revision"] += 1

    def _resources(self, s, recipe):
        require(recipe["tool"] in s.get("available_tools", self.config["initial"]["available_tools"]), "tool unavailable")
        for item, count in recipe["ingredients"].items():
            require(self.config["objects"][item]["parent"] == s["place"], "ingredient not at current place")
            require(s["inventory"].get(item, 0) >= count, "insufficient ingredients")

    def _reading_call(self, db, evidence):
        require(self.store.read(db).get("cognition_enabled"), "P2 not enabled for model result")
        call_id = evidence.get("model_call_id")
        require(isinstance(call_id, str) and call_id.endswith(":read"), "missing reading call provenance")
        row = db.execute("SELECT stage,request,kind,status,response FROM life_model_calls WHERE id=?", (call_id,)).fetchone()
        require(row is not None and row[0] == "read" and row[3] == "received", "unverified reading call")
        payload, output = json.loads(row[1])["payload"], json.loads(row[4])
        guard = db.execute("SELECT status,response FROM life_model_calls WHERE id=?", (call_id[:-5] + ":guard",)).fetchone()
        require(guard is not None and guard[0] == "received", "missing reading boundary check")
        checked = json.loads(guard[1])
        require(checked.get("approved") is True and checked.get("issues") == [], "reading boundary check failed")
        require(all(payload["content"][key] == evidence.get(key) for key in ("start", "end", "text", "content_version"))
                and output.get("note") == evidence.get("note"), "reading evidence differs from model call")
        return {"kind": row[2], "activity_id": payload["activity_id"], "checkpoint": payload["state"]}

    def _result(self, s, result, result_id, at, db):
        require(result["activity_id"] in s["activities"], "unknown activity")
        a = s["activities"][result["activity_id"]]
        require(a.get('reading_mode') != 'structure_simulation', 'structure-only reading uses clock settlement, not content results')
        require(a.get('viewing_mode') != 'active_time_simulation', 'movie skill uses active-time settlement')
        require(not a.get('outing_mode'), 'outing uses lifecycle events')
        require(not a.get('rest_mode'), 'rest records start/end events only')
        require(not a.get('television_mode'), 'television records switch events only')
        require(not a.get('exercise_mode'), 'exercise uses active-time settlement')
        require(not a.get('housework_mode'), 'housework uses active-time settlement')
        require(not a.get('work_mode'), 'daily work uses active-time phases, not legal artifacts')
        require(not a.get('care_mode'), 'care skill uses active-time settlement')
        require(not a.get('meal_mode'), 'meal skill uses active-time settlement')
        require(a["status"] == "running" and s["active"] == a["id"], "activity not running")
        require(at >= utc(a["next_due_at"]), "checkpoint not reached")
        require((at - utc(a["last_progress_at"])).total_seconds() <= self.config["max_gap_seconds"],
                "time gap requires explicit recovery; no offline settlement")
        e = result["evidence"]
        model_provenance = None
        if e.get("source") == "model_work":
            from .work_artifacts import provenance
            work_context = provenance(self, db, e)
            require(a["kind"] == "work" and work_context["activity_id"] == a["id"], "work activity mismatch")
            require(utc(work_context["now"]) == at, "work occurrence time changed")
            require(self._effect_inputs(s, a["id"]) == self._effect_inputs(work_context["state"], a["id"]), "work inputs changed")
        elif e.get("source") == "model_reading":
            model_provenance = self._reading_call(db, e)
            require(a["kind"] == "reading" and a["id"] == model_provenance["activity_id"], "model result activity mismatch")
        elif e.get("source") == "simulated_world":
            from .home_world import verify
            check = verify(self, db, e)
            require(check["activity_id"] == a["id"] and check["at"] == at.isoformat(), "world activity/time mismatch")
            require(self._effect_inputs(s, a["id"]) == self._effect_inputs(check["snapshot"], a["id"]), "world effect inputs changed")
            e = {k: v for k, v in e.items() if k != "world_check_id"}
        else:
            require(e.get("source") == "controlled_test", "not a controlled result")
        if a["kind"] == "watching":
            require(e.get('source')=='simulated_world' and set(e)=={'source','seconds','observation'}, 'viewing needs simulator evidence')
            require(e['seconds']==self.config['checkpoint_seconds'], 'invalid viewing checkpoint duration')
            a['progress'] += e['seconds']
            s.setdefault('viewing', {})[a['target']] = a['progress']
            duration = self.config['movies'][a['target']].get('duration_seconds')
            complete = bool(duration and a['progress'] >= duration)
        elif a["kind"] == "work":
            require(e.get("source") == "model_work", "work requires validated model artifact")
            job = s["work_items"][a["target"]]; artifact = e["artifact"]
            require(job["progress"] == a["progress"] and artifact["stage"] == a["progress"]+1, "noncontiguous work")
            require(job["materials_hash"] == digest(self.config["work_items"][a["target"]]), "work material hash mismatch")
            job["artifacts"].append({"result_id": result_id, "work_call_id": e["work_call_id"], "artifact": artifact})
            a["progress"] = job["progress"] = artifact["stage"]
            complete = a["progress"] == 2
            job["status"] = "completed" if complete else "in_progress"
        elif a["kind"] == "reading":
            fields = {"source", "start", "end", "text", "content_version", "note"}
            if model_provenance:
                fields.add("model_call_id")
            require(set(e) == fields, "invalid reading evidence")
            book = self.config["books"][a["target"]]
            require(type(e["start"]) is int and type(e["end"]) is int, "integer offsets required")
            require(e["content_version"] == a["content_version"], "content version mismatch")
            require(s["reading"].get(a["progress_key"], 0) == a["progress"], "shared reading progress changed")
            require(e["start"] == a["progress"] < e["end"] <= len(book["text"]), "noncontiguous/repeated reading")
            require(e["text"] == book["text"][e["start"]:e["end"]]
                    and isinstance(e["note"], str) and bool(e["note"].strip()), "missing processed content")
            record = {"actor_id": self.config["persona"]["id"], "book": a["target"], "result_id": result_id,
                      "root_result_id": result.get("root_result_id", result_id),
                      "content_hash": a["content_hash"], "occurred_at": at.isoformat(), **e}
            if model_provenance:
                record["model_kind"] = model_provenance["kind"]
            db.execute("INSERT INTO life_evidence(category,id,body) VALUES('reading',?,?)", (result_id, canonical(record)))
            a["progress"] = e["end"]
            s["reading"][a["progress_key"]] = e["end"]
            complete = e["end"] == len(book["text"])
        elif a["kind"] == "cooking":
            require(set(e) == {"source", "step", "observation"}, "invalid cooking evidence")
            recipe = self.config["recipes"][a["target"]]
            require(type(e["step"]) is int and e["step"] == a["progress"] + 1 <= len(recipe["steps"]), "invalid cooking progress")
            require(isinstance(e["observation"], str) and bool(e["observation"].strip()), "missing cooking observation")
            require(recipe["tool"] in s.get("available_tools", self.config["initial"]["available_tools"]), "tool unavailable")
            if not a["ingredients_consumed"]:
                self._resources(s, recipe)
                for item, count in recipe["ingredients"].items():
                    s["inventory"][item] -= count
                a["ingredients_consumed"] = True
            a["progress"] = e["step"]
            complete = a["progress"] == len(recipe["steps"])
            if complete:
                s["meals"][a["id"]] = {"remaining": 1.0, "place": a["place"], "source_result": result_id}
        elif a["kind"] in {"moving", "serving"}:
            require(e.get("source") == "simulated_world" and set(e) == {"source", "from", "to", "observation"}, "movement needs simulator evidence")
            require(a["route"][a["progress"]:a["progress"]+2] == [e["from"], e["to"]]
                    and s["place"] == e["from"], "noncontiguous movement")
            if a["kind"] == "serving":
                meal = s["meals"][a["target"]]
                require(meal["place"] == e["from"] and meal["remaining"] > 0, "carried food changed")
                meal["place"] = e["to"]
            s["place"] = a["place"] = e["to"]
            a["progress"] += 1
            complete = a["progress"] == len(a["route"])-1
        elif a["kind"] == "showering":
            require(set(e) == {"source", "observation"} and e["source"] == "simulated_world",
                    "shower needs simulator evidence")
            require(a["place"] == self.config["daily_routines"]["shower"]["place"], "shower place changed")
            require(isinstance(e["observation"], str) and bool(e["observation"].strip()), "missing shower observation")
            a["progress"] = 1
            complete = True
        else:
            fields = {"source", "portion", "observation"}
            if not s.get("cognition_enabled"):
                fields.add("hunger_after")
            require(set(e) == fields, "invalid eating evidence")
            require(type(e["portion"]) in (int, float) and 0 < e["portion"] <= 1, "invalid portion")
            if not s.get("cognition_enabled"):
                require(type(e["hunger_after"]) in (int, float) and 0 <= e["hunger_after"] <= 10, "invalid test hunger")
            require(isinstance(e["observation"], str) and bool(e["observation"].strip()), "missing eating observation")
            meal = s["meals"][a["target"]]
            require(e["portion"] <= meal["remaining"], "food already consumed")
            meal["remaining"] = round(meal["remaining"] - e["portion"], 8)
            a["progress"] += e["portion"]
            # Explicit test result, NOT a physiological rate or D2A model update.
            if not s.get("cognition_enabled"):
                s["test_hunger"] = e["hunger_after"]
            complete = meal["remaining"] == 0
        a["last_progress_at"] = at.isoformat()
        a["revision"] += 1
        a["next_due_at"] = None if complete else self._due_at(at, a)
        if complete:
            a.update(status="completed", completed_at=at.isoformat())
            s["active"] = None
