"""Isolated P2 coordinator. GA/D2A mechanisms adapted to P1 transactions.

No fallback candidates or canned inference. Failed mandatory stages remain
blocking; optional reflection rejection is audited with persisted backoff.
"""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .clock import utc
from .config import canonical, digest
from .activity_engine import require
from .store import Conflict
from .cognition_contracts import refs, settings, shape, text, texts, validate_settings
from .memory_service import LifeMemory, add_memory
from .model_client import RecordedCalls, ModelError


class Cognition:
    def __init__(self, prototype, model, config=None, calendar_provider=None):
        self.p = prototype
        self.store, self.clock = prototype.store, prototype.clock
        from .state_schema import facts_only, current_state
        self.config = facts_only(settings() if config is None else deepcopy(config))
        self.calendar_provider = calendar_provider
        validate_settings(self.config)
        self.persona = {**self.p.config["persona"], **json.loads(Path(__file__).with_name("persona.json").read_text(encoding="utf-8"))}
        self.calls = RecordedCalls(self.store, model)
        with self.store.connect() as db:
            db.executescript(Path(__file__).with_name("cognition_schema.sql").read_text(encoding="utf-8"))
            db.execute("BEGIN IMMEDIATE")
            row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'cognition\') AS life_cognition_state WHERE id=1').fetchone()
            if row:
                require(facts_only(json.loads(row[0])["config"]) == self.config, "P2 configuration changed; use another run")
                require(json.loads(row[0])["persona_hash"] == digest(self.persona), "fixed persona changed; use another run")
                meta=json.loads(row[0]);meta['config']=self.config
                self._save_meta(db,meta)
                before=self.store.read(db);after=current_state(before)
                if after!=before:
                    after['revision']+=1
                    db.execute("UPDATE life_state SET body=? WHERE name='current'",(canonical(after),))
            else:
                state = self.store.read(db)
                meta = {"revision": 0, "config": self.config, "cursor": 0, "reflection_budget": 0,
                        "persona_hash": digest(self.persona),
                        "enabled_after_event": db.execute("SELECT COALESCE(MAX(rowid),0) FROM (SELECT rowid,id,request,receipt FROM life_receipts WHERE category='event_control')").fetchone()[0]}
                state.pop("test_hunger", None)
                production = self.p.config.get("mode") == "local_single_user"
                state.update(cognition_enabled=True, revision=state["revision"]+1)
                db.execute("UPDATE life_state SET body=?  WHERE name='current' AND ( id=1)", (canonical(state),))
                db.execute("INSERT INTO life_state(name,id,body) VALUES('cognition',1,?)", (canonical(meta),))
                if not production:
                    self._observe(db, "p2:initial", {"type": "initial_condition", "fact": {
                        "place": state["place"], "basis": "explicit test initial condition, not a generated experience"},
                        "occurred_at": self.clock.now().isoformat(),
                        "knowledge_basis": "test_fixture_self_location"})
        self.memory = LifeMemory(self.store, self.config)
        from .coarse_plan import DailyAgenda
        self.agenda = DailyAgenda(self)

    @staticmethod
    def _meta(db):
        return json.loads(db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'cognition\') AS life_cognition_state WHERE id=1').fetchone()[0])

    @staticmethod
    def _save_meta(db, meta):
        db.execute("UPDATE life_state SET body=?  WHERE name='cognition' AND ( id=1)", (canonical(meta),))

    def _observe(self, db, event_id, observation):
        observation_id = "obs:" + event_id
        if db.execute("SELECT 1 FROM life_observations WHERE id=?", (observation_id,)).fetchone():
            return
        actor = self.p.config["persona"]["id"]
        observation.update(id=observation_id, actor_id=actor, source_event=event_id)
        description = canonical(observation["fact"])
        db.execute("INSERT INTO life_observations VALUES(?,?,?,0)", (observation_id, event_id, canonical(observation)))
        add_memory(db, "mem:" + event_id, "event", description, observation["occurred_at"], 1,
                   [observation["type"]], [observation_id], actor, "pending_importance")

    def ingest(self):
        """Only committed self-known P1 outcomes/control, never proposals or staged results."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            meta, state = self._meta(db), self.store.read(db)
            rows = db.execute("SELECT rowid,id,request,receipt FROM (SELECT rowid,id,request,receipt FROM life_receipts WHERE category='event_control') WHERE rowid>? ORDER BY rowid", (meta["cursor"],)).fetchall()
            for index, event_id, raw, receipt in rows:
                request, receipt = json.loads(raw), json.loads(receipt)
                op = request["operation"]
                if op == 'companionship' or (op == 'coarse_state' and request.get('fact', {}).get('activity') == 'user_time'):
                    # A reserved slot is evidence of an arrangement, not of a
                    # completed shared activity. Use immutable event-time facts.
                    event = db.execute('SELECT description FROM events WHERE id=?', (event_id,)).fetchone()
                    if event:
                        fact = {'description': event[0],
                                'semantics': '陪伴约定或状态记录；不据此推断用户在场、活动成果或影片已看完。'}
                        detail = request.get('companion') if op == 'companionship' else request['fact']
                        keywords = ['陪伴']
                        if detail:
                            fact['companion' if op == 'companionship' else 'reservation'] = detail
                            if detail.get('title'):
                                keywords.append(detail['title'])
                        add_memory(db, 'mem:'+event_id, 'event', canonical(fact), receipt['occurred_at'], 1,
                                   keywords, [event_id], self.p.config['persona']['id'], 'observed')
                    meta['cursor'] = index
                    meta['revision'] += 1
                    continue
                outing_id=receipt.get('outing_session_ended') or request.get('payload',{}).get('activity_id')
                if state['activities'].get(outing_id,{}).get('outing_mode') and op in {'start','interrupt','fail','recover'}:
                    event=db.execute('SELECT description FROM events WHERE id=?',(event_id,)).fetchone()
                    if event: add_memory(db,'mem:'+event_id,'event',event[0],receipt['occurred_at'],1,['外出'],[event_id],self.p.config['persona']['id'],'observed')
                    meta['cursor']=index;meta['revision']+=1
                    continue
                rest_id=receipt.get('rest_session_ended') or request.get('payload',{}).get('activity_id')
                if state['activities'].get(rest_id,{}).get('rest_mode') and op in {'start','interrupt','fail','recover'}:
                    event=db.execute('SELECT description FROM events WHERE id=?',(event_id,)).fetchone()
                    if event: add_memory(db,'mem:'+event_id,'event',event[0],receipt['occurred_at'],1,['休息'],[event_id],self.p.config['persona']['id'],'observed')
                    meta['cursor']=index;meta['revision']+=1
                    continue
                television_id=receipt.get('television_session_ended') or request.get('payload',{}).get('activity_id')
                if state['activities'].get(television_id,{}).get('television_mode') and op in {'start','interrupt','fail','recover'}:
                    event=db.execute('SELECT description FROM events WHERE id=?',(event_id,)).fetchone()
                    if event: add_memory(db,'mem:'+event_id,'event',event[0],receipt['occurred_at'],1,['看电视'],[event_id],self.p.config['persona']['id'],'observed')
                    meta['cursor']=index;meta['revision']+=1
                    continue
                exercise_id=receipt.get('exercise_session_ended') or request.get('activity_id') or request.get('payload',{}).get('activity_id')
                if op=='exercise_departure' or (state['activities'].get(exercise_id,{}).get('exercise_mode') and op in {'start','resume','interrupt','fail','recover'}):
                    event=db.execute('SELECT description FROM events WHERE id=?',(event_id,)).fetchone()
                    if event: add_memory(db,'mem:'+event_id,'event',event[0],receipt['occurred_at'],1,['运动'],[event_id],self.p.config['persona']['id'],'observed')
                    meta['cursor']=index;meta['revision']+=1
                    continue
                work_id=receipt.get('work_session_ended') or request.get('activity_id') or request.get('payload',{}).get('activity_id')
                if op=='work_departure' or (state['activities'].get(work_id,{}).get('work_mode') and op in {'start','resume','interrupt','fail','recover'}):
                    event=db.execute('SELECT description FROM events WHERE id=?',(event_id,)).fetchone()
                    if event:add_memory(db,'mem:'+event_id,'event',event[0],receipt['occurred_at'],1,['工作'],[event_id],self.p.config['persona']['id'],'observed')
                    meta['cursor']=index;meta['revision']+=1
                    continue
                housework_id=receipt.get('housework_session_ended') or request.get('payload',{}).get('activity_id')
                if op=='household_timer' or (state['activities'].get(housework_id,{}).get('housework_mode') and op in {'start','resume','interrupt','fail','recover'}):
                    event=db.execute('SELECT description FROM events WHERE id=?',(event_id,)).fetchone()
                    if event: add_memory(db,'mem:'+event_id,'event',event[0],receipt['occurred_at'],1,
                                         ['家务'],[event_id],self.p.config['persona']['id'],'observed')
                    meta['cursor']=index;meta['revision']+=1
                    continue
                care_id=receipt.get('care_session_ended') or request.get('payload',{}).get('activity_id')
                if state['activities'].get(care_id,{}).get('care_mode') and op in {'start','resume','interrupt','fail','recover'}:
                    if receipt.get('care_completed'):
                        fact=receipt['care_completed']
                        self._observe(db,event_id,{'type':'care_completed','fact':fact,
                            'occurred_at':receipt['occurred_at'],
                            'knowledge_basis':'committed_active_time_care_completion'})
                    else:
                        event=db.execute('SELECT description FROM events WHERE id=?',(event_id,)).fetchone()
                        if event: add_memory(db,'mem:'+event_id,'event',event[0],receipt['occurred_at'],1,
                                             ['个人护理'],[event_id],self.p.config['persona']['id'],'observed')
                    meta['cursor']=index;meta['revision']+=1
                    continue
                meal_id = receipt.get('meal_session_ended') or request.get('payload',{}).get('activity_id')
                if state['activities'].get(meal_id,{}).get('meal_mode') and op in {'start','resume','interrupt','fail','recover'}:
                    if receipt.get('meal_completed'):
                        self._observe(db,event_id,{'type':'meal_completed','fact':receipt['meal_completed'],
                            'occurred_at':receipt['occurred_at'],
                            'knowledge_basis':'committed_active_time_meal_completion'})
                    else:
                        event = db.execute('SELECT description FROM events WHERE id=?',(event_id,)).fetchone()
                        if event:
                            add_memory(db,'mem:'+event_id,'event',event[0],receipt['occurred_at'],1,
                                       ['饮食'],[event_id],self.p.config['persona']['id'],'observed')
                    meta['cursor']=index
                    meta['revision']+=1
                    continue
                movie_id = receipt.get('viewing_session_ended') or request.get('payload', {}).get('activity_id')
                movie_activity = state['activities'].get(movie_id, {})
                if movie_activity.get('viewing_mode') == 'active_time_simulation' and op in {'start','resume','interrupt','fail','recover'}:
                    event = db.execute('SELECT description FROM events WHERE id=?', (event_id,)).fetchone()
                    if event:
                        add_memory(db, 'mem:'+event_id, 'event', event[0], receipt['occurred_at'], 1,
                            ['观影', self.p.config['movies'][movie_activity['target']]['title']],
                            [event_id], self.p.config['persona']['id'], 'observed')
                    meta['cursor'] = index
                    meta['revision'] += 1
                    continue
                reading_id = receipt.get('reading_session_ended') or request.get('payload', {}).get('activity_id')
                reading_activity = state['activities'].get(reading_id, {})
                if reading_activity.get('reading_mode') == 'structure_simulation' and op in {'start','resume','interrupt','fail','recover'}:
                    # These are timed simulation facts, not textual comprehension.
                    # Store the immutable event directly; no assimilation/guard LLM.
                    event = db.execute('SELECT description FROM events WHERE id=?', (event_id,)).fetchone()
                    if event:
                        add_memory(db, 'mem:'+event_id, 'event', event[0], receipt['occurred_at'], 1,
                            ['阅读', self.p.config['books'][reading_activity['target']]['title']],
                            [event_id], self.p.config['persona']['id'], 'observed')
                    meta['cursor'] = index
                    meta['revision'] += 1
                    continue
                if op == "p3":
                    self._observe(db, event_id, deepcopy(request["observation"]))
                    meta["revision"] += 1
                if op in {"start", "interrupt", "resume", "fail", "result"}:
                    activity_id = request["activity_id"] if op == "result" else request["payload"]["activity_id"]
                    a = state["activities"][activity_id]
                    fact = {"actor": self.p.config["persona"]["id"], "operation": op,
                            "activity_id": activity_id, "kind": a["kind"], "target": a["target"]}
                    if op == "result":
                        fact["actual_result"] = {k: v for k, v in request["evidence"].items() if k != "hunger_after"}
                        fact["root_result_id"] = request.get("root_result_id", event_id)
                    elif op == "fail":
                        fact["feedback"] = request["payload"]["reason"]
                    self._observe(db, event_id, {"type": "failure" if op == "fail" else "self_activity",
                        "fact": fact, "occurred_at": receipt["occurred_at"],
                        "knowledge_basis": "committed_self_action_or_received_failure_feedback",
                        "historical_before_p2": index <= meta["enabled_after_event"]})
                    meta["revision"] += 1
                meta["cursor"] = index
            self._save_meta(db, meta)

    def _snapshot(self):
        now = self.clock.now()
        timezone_name = self.p.config.get("display_timezone", "Asia/Shanghai")
        with self.store.connect() as db:
            db.execute("BEGIN")
            state, meta = self.store.read(db), self._meta(db)
        return {"state": state, "meta_revision": meta["revision"], "persona": self.persona,
                # UTC remains the comparison/storage clock.  The explicit
                # civil time prevents a model stage from treating a UTC hour
                # as the character's local hour.
                "now": now.isoformat(),
                "local_now": now.astimezone(ZoneInfo(timezone_name)).isoformat(),
                "timezone": timezone_name,
                "config_source": self.config["source"], "unknown_user_state": None}

    def _fresh(self, db, context):
        state, meta = self.store.read(db), self._meta(db)
        if state["revision"] != context["state"]["revision"] or meta["revision"] != context["meta_revision"]:
            raise Conflict("P2 inputs changed; retain attempt and explicitly re-evaluate with a new id")
        return state, meta

    def _prepare(self, run_id, kind, builder):
        with self.store.connect() as db:
            row = db.execute("SELECT kind,context,status,receipt FROM life_cognition_runs WHERE id=?", (run_id,)).fetchone()
        if row:
            require(row[0] == kind, "P2 run id reused")
            require(row[2] != "rejected", "rejected P2 attempt; use new explicit attempt id")
            return json.loads(row[1]), json.loads(row[3]) if row[3] else None
        context = builder()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._fresh(db, context)
            db.execute("INSERT INTO life_cognition_runs VALUES(?,?,?,'prepared',NULL)", (run_id, kind, canonical(context)))
        return context, None

    def _reject(self, run_id, exc):
        with self.store.connect() as db:
            db.execute("UPDATE life_cognition_runs SET status='rejected',receipt=? WHERE id=? AND status='prepared'",
                       (canonical({"error": type(exc).__name__, "detail": str(exc)}), run_id))

    @staticmethod
    def _finish(db, run_id, receipt):
        db.execute("UPDATE life_cognition_runs SET status='committed',receipt=? WHERE id=?", (canonical(receipt), run_id))

    def _guard(self, call_id, stage, context, output):
        checked = self.calls.ask(call_id, "guard", {"stage": stage, "context": context, "proposed": output})
        shape(checked, {"approved", "issues"})
        require(type(checked["approved"]) is bool and isinstance(checked["issues"], list), "invalid guard output")
        require(checked["approved"] and not checked["issues"], "semantic boundary check rejected output: " + canonical(checked["issues"]))

    def assimilate(self, observation_id, attempt_id):
        def build():
            context = self._snapshot()
            with self.store.connect() as db:
                row = db.execute("SELECT body FROM life_observations WHERE id=?", (observation_id,)).fetchone()
            require(row is not None, "unknown observation; predictions are not observations")
            context["observation"] = json.loads(row[0])
            fact = context['observation'].get('fact',{})
            if fact.get('kind')=='reading' and fact.get('operation')=='result':
                with self.store.connect() as db:
                    result=db.execute('SELECT body,receipt FROM results WHERE id=?',
                        (context['observation']['source_event'].removeprefix('result:'),)).fetchone()
                require(result is not None and result[1] and
                    fact['actual_result']=={k:v for k,v in json.loads(result[0])['evidence'].items() if k!='hunger_after'},
                    'reading observation requires unchanged settled result')
            from .event_assimilation import control_event_evidence
            with self.store.connect() as db:
                context['control_event_evidence']=control_event_evidence(self.p,db,context['observation'])
            from .movement_evidence import evidence
            with self.store.connect() as db:
                context["movement_evidence"] = evidence(self.p, db, context["observation"])
            if context["movement_evidence"]:
                context["movement_place_names"] = {k: v["name"] for k, v in self.p.config["places"].items()}
                with self.store.connect() as db:
                    rejected = db.execute("SELECT id,receipt FROM life_cognition_runs WHERE kind=? AND status='rejected' ORDER BY rowid DESC LIMIT 1",
                                          ("assimilate:"+observation_id,)).fetchone()
                    if rejected:
                        output = db.execute("SELECT response FROM life_model_calls WHERE id=?", (rejected[0]+":update",)).fetchone()
                        parsed = db.execute("SELECT response FROM life_model_calls WHERE id=?", (rejected[0]+":movement-expression",)).fetchone()
                        context["movement_validation_feedback"] = {"role": "rejected_output_not_world_evidence",
                            "error": json.loads(rejected[1]), "rejected_summary": json.loads(output[0]).get("summary") if output and output[0] else None,
                            "independent_prose_parse": json.loads(parsed[0]) if parsed and parsed[0] else None}
            return context
        with self.store.connect() as db:
            done = db.execute('SELECT body FROM (SELECT rowid,"id" AS "observation_id","body" AS "body" FROM life_evidence WHERE category=\'observation_update\') AS life_observation_updates WHERE observation_id=?', (observation_id,)).fetchone()
        if done:
            return json.loads(done[0])
        context, done = self._prepare(attempt_id, "assimilate:" + observation_id, build)
        if done:
            return done
        try:
            from .event_assimilation import observation_input, validate_update
            payload = observation_input(context)
            control_fact=bool(payload.get('control_event_evidence'))
            deterministic_p3 = bool(control_fact and payload['control_event_evidence'].get('event_type'))
            if deterministic_p3:
                # The immutable P3 event and receipt own sleep/wake/runtime
                # facts. Commit them without waiting for optional model prose.
                from .event_assimilation import control_factual_output
                original_output = None
                output = control_factual_output(payload)
            else:
                output = self.calls.ask(attempt_id + ":update", "assimilate", payload)
                original_output = output
            if control_fact and not deterministic_p3:
                from .event_assimilation import control_factual_output
                output=control_factual_output(payload,output)
            reading_fact = payload.get('event_scope', {}).get('actual_action') == 'reading'
            if reading_fact:
                from .event_assimilation import reading_factual_output
                output = reading_factual_output(payload, output)
            if payload.get("movement_evidence"):
                from .movement_evidence import factual_output
                output = factual_output(payload, output)
            validate_update(output, payload)
            deterministic_fact = bool(payload.get("movement_evidence") or reading_fact or control_fact)
            guard_payload = ({**payload, "summary_contract":
                "code_generated_verified_event_not_dialogue; natural prose is optional and separately quarantined"}
                if deterministic_fact else payload)
            optional_guard = None
            if deterministic_p3:
                optional_guard={"status":"not_generated","error":None}
            elif control_fact or reading_fact:
                # The executor/source checks and validate_update own necessary facts.
                # A semantic model reviews only the model's optional wording; its
                # rejection cannot invalidate the already verified event.
                try:
                    if reading_fact:
                        from .event_assimilation import validate_optional_reading_prose
                        validate_optional_reading_prose(original_output)
                    self._guard(attempt_id + ":optional-prose-guard", "assimilate",
                        {**payload,"summary_contract":"optional_model_wording_only_not_state_authority"},original_output)
                    optional_guard={"status":"approved","error":None}
                except Exception as exc:
                    optional_guard={"status":"pending_review","error":type(exc).__name__+": "+str(exc)}
            else:
                if not payload.get("movement_evidence"):
                    self._guard(attempt_id + ":guard", "assimilate", guard_payload, output)
            prose_review = None
            if control_fact:
                with self.store.connect() as db:
                    db.execute("INSERT INTO life_evidence(category,id,kind,body) VALUES('cognition',?,'control_prose_review',?)",(attempt_id+':control-prose-review',canonical({
                        'observation_id':observation_id,'original_output':original_output,'status':optional_guard['status'],
                        'semantic_review_error':optional_guard['error'],
                        'effect':'optional prose not published; command and receipt verified independently; necessary state does not depend on prose'})))
            if reading_fact:
                with self.store.connect() as db:
                    db.execute("INSERT INTO life_evidence(category,id,kind,body) VALUES('cognition',?,'reading_prose_review',?)", (attempt_id+':reading-prose-review', canonical({
                        'observation_id':observation_id,'original_output':original_output,'status':optional_guard['status'],
                        'semantic_review_error':optional_guard['error'],
                        'effect':'optional reading prose not published; executor character facts used; necessary state does not depend on prose'})))
            if payload.get("movement_evidence"):
                from .movement_evidence import review_optional_expression
                prose_review = review_optional_expression(self, attempt_id, payload, original_output)
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute('SELECT body FROM (SELECT rowid,"id" AS "observation_id","body" AS "body" FROM life_evidence WHERE category=\'observation_update\') AS life_observation_updates WHERE observation_id=?', (observation_id,)).fetchone()
                if existing:
                    return json.loads(existing[0])
                state, meta = self._fresh(db, context)
                state["revision"] += 1
                receipt = {"observation_id": observation_id, "state_revision": state["revision"],
                           "source_event": context["observation"]["source_event"], "call_id": attempt_id + ":update",
                           "model_kind": "code_verified" if deterministic_p3 else self.calls.model.kind,
                           "summary": output["summary"],
                           "occurred_at": context["observation"]["occurred_at"], "recorded_at": self.clock.now().isoformat()}
                if payload.get("movement_evidence"): receipt["movement_facts"] = output["movement_facts"]
                if prose_review:
                    receipt.update(summary_source="code_generated_verified_movement_event_not_character_dialogue",
                                   optional_prose_status=prose_review["status"], prose_review_id=attempt_id+":prose-review")
                db.execute("UPDATE life_state SET body=?  WHERE name='current' AND ( id=1)", (canonical(state),))
                db.execute("INSERT INTO life_evidence(category,id,body) VALUES('observation_update',?,?)", (observation_id, canonical(receipt)))
                db.execute("UPDATE life_observations SET processed=1 WHERE id=?", (observation_id,))
                db.execute("UPDATE life_memories SET importance=?,keywords=?,status='observed' WHERE id=?",
                           (output["importance"], canonical(output["keywords"]), "mem:" + context["observation"]["source_event"]))
                meta["reflection_budget"] += output["importance"]
                meta["revision"] += 1
                self._save_meta(db, meta)
                self._finish(db, attempt_id, receipt)
            return receipt
        except Exception as exc:
            self._reject(attempt_id, exc)
            raise

    def synchronize(self, attempt_prefix):
        self.ingest()
        with self.store.connect() as db:
            pending = [r[0] for r in db.execute("SELECT id FROM life_observations WHERE processed=0 ORDER BY rowid")]
        return [self.assimilate(obs, attempt_prefix + ":" + digest(obs)[:16]) for obs in pending]

    def reflect(self, attempt_id):
        with self.store.connect() as db:
            done = db.execute("SELECT status,receipt FROM life_cognition_runs WHERE id=?", (attempt_id,)).fetchone()
            if done and done[0] == "committed":
                return json.loads(done[1])
            meta = self._meta(db)
        if meta["reflection_budget"] < self.config["reflection_threshold"]:
            return {"status": "not_due", "budget": meta["reflection_budget"]}
        def build():
            context = self._snapshot()
            with self.store.connect() as db:
                context["recent"] = [{"id": r[0], "description": r[1]} for r in db.execute(
                    "SELECT id,description FROM life_memories WHERE status='observed' ORDER BY created_at DESC,id LIMIT 100")]
                context["budget"] = self._meta(db)["reflection_budget"]
            return context
        context, done = self._prepare(attempt_id, "reflection", build)
        if done:
            return done
        try:
            focal = self.calls.ask(attempt_id + ":focal", "focal", context)
            shape(focal, {"questions"}); texts(focal["questions"])
            require(len(focal["questions"]) <= 3, "too many focal questions")
            memories = {}
            for index, query in enumerate(focal["questions"]):
                for memory in self.memory.retrieve(query, attempt_id + ":retrieve:" + str(index)):
                    memories[memory["id"]] = memory
            reflection_context = {**context, "questions": focal["questions"], "memories": list(memories.values())}
            state_id = "state-evidence:" + attempt_id + ":" + str(context["state"]["revision"])
            from .memory_reflection import memory_evidence, state_evidence as snapshot_evidence, guard_context
            state_evidence = snapshot_evidence(context, state_id)
            with self.store.connect() as db:
                reflection_context["evidence_catalog"] = [memory_evidence(db, m) for m in memories.values()] + [state_evidence]
                db.execute("INSERT OR IGNORE INTO life_evidence(category,id,kind,body) VALUES('cognition',?,?,?)",
                           (state_id, "reflection_state_evidence", canonical(state_evidence)))
                require(db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","kind" AS "kind","body" AS "body" FROM life_evidence WHERE category=\'cognition\') AS life_cognition_artifacts WHERE id=?', (state_id,)).fetchone()[0] == canonical(state_evidence),
                        "state evidence changed under the same id")
            output = self.calls.ask(attempt_id + ":reflect", "reflect", reflection_context)
            shape(output, {"insights"})
            require(isinstance(output["insights"], list) and 1 <= len(output["insights"]) <= 3, "invalid reflections")
            for insight in output["insights"]:
                shape(insight, {"description", "importance", "keywords", "evidence_ids"})
                text(insight["description"]); texts(insight["keywords"])
                refs(insight["evidence_ids"], set(memories) | {state_id})
                require(type(insight["importance"]) is int and 1 <= insight["importance"] <= 10, "invalid importance")
            self._guard(attempt_id + ":guard", "reflection", guard_context(reflection_context, output), output)
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                state, meta = self._fresh(db, context)
                ids = []
                for index, insight in enumerate(output["insights"]):
                    memory_id = "thought:" + attempt_id + ":" + str(index)
                    add_memory(db, memory_id, "thought", insight["description"], self.clock.now().isoformat(),
                               insight["importance"], insight["keywords"], insight["evidence_ids"],
                               self.p.config["persona"]["id"], "inference")
                    ids.append(memory_id)
                meta["reflection_budget"] -= context["budget"]
                meta["revision"] += 1
                self._save_meta(db, meta)
                receipt = {"status": "committed", "memory_ids": ids, "model_kind": self.calls.model.kind}
                self._finish(db, attempt_id, receipt)
            return receipt
        except Exception as exc:
            self._reject(attempt_id, exc)
            raise

    @staticmethod
    def _decision_ready(db):
        # Staging a result need not change the snapshot revision. Check separately,
        # including inside the final decision transaction (concurrent staging).
        require(not db.execute("SELECT 1 FROM result_controls WHERE status='pending'").fetchone(),
                "necessary result unsettled; explicit P1 result review required")
        require(not db.execute("SELECT 1 FROM life_observations WHERE processed=0").fetchone(),
                "necessary observation not assimilated")

    def optional_reflect(self, attempt_id):
        """Bounded, persisted deferral; only optional model/contract errors degrade.

        State conflicts, DB errors and necessary settlement failures still escape.
        Direct reflect() remains strict for explicit review and local validation.
        """
        from .memory_reflection import RETRY_BASE_SECONDS, RETRY_CAP_SECONDS
        context = self._snapshot()
        with self.store.connect() as db:
            self._decision_ready(db)
            prior = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","kind" AS "kind","body" AS "body" FROM life_evidence WHERE category=\'cognition\') AS life_cognition_artifacts WHERE kind=\'reflection_retry\' ORDER BY rowid DESC LIMIT 1').fetchone()
        prior = json.loads(prior[0]) if prior else {}
        if prior.get("status") == "pending_retry" and self.clock.now() < utc(prior["retry_after"]):
            return {"status": "deferred", "failed_attempt": prior["attempt_id"], "retry_after": prior["retry_after"]}
        try:
            receipt = self.reflect(attempt_id)
        except Conflict:
            raise
        except (ValueError, ModelError) as exc:
            count = prior.get("consecutive_failures", 0) + 1
            delay = min(RETRY_CAP_SECONDS, RETRY_BASE_SECONDS * 2 ** min(count-1, 8))
            receipt = {"status": "pending_retry", "attempt_id": attempt_id,
                "error": {"type": type(exc).__name__, "detail": str(exc)},
                "consecutive_failures": count, "failed_at": self.clock.now().isoformat(),
                "retry_after": (self.clock.now()+timedelta(seconds=delay)).isoformat(),
                "input_state_revision": context["state"]["revision"],
                "policy_source": "project_adaptation_isolated_test_default_300s_exponential_cap3600s"}
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self._fresh(db, context)
                self._decision_ready(db)
                db.execute("INSERT INTO life_evidence(category,id,kind,body) VALUES('cognition',?,?,?)",
                           (attempt_id+":retry", "reflection_retry", canonical(receipt)))
            return receipt
        if receipt["status"] == "committed":
            with self.store.connect() as db:
                db.execute("INSERT OR IGNORE INTO life_evidence(category,id,kind,body) VALUES('cognition',?,?,?)", (attempt_id+":retry", "reflection_retry",
                    canonical({"status": "resolved", "attempt_id": attempt_id, "consecutive_failures": 0,
                               "receipt": receipt, "prior_failed_attempt": prior.get("attempt_id")})))
        return receipt

    def inspect(self):
        from .storage_layout import audit_cursor
        with self.store.connect() as db:
            db.execute("BEGIN")
            output = {"state": self.store.read(db), "meta": self._meta(db)}
            for table in ("life_observations", "life_memories", "life_observation_updates", "life_model_calls", "life_cognition_runs", "life_memory_retrievals", "life_cognition_artifacts"):
                cur = audit_cursor(db, table)
                output[table] = [dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]
            from .movement_evidence import summary_view
            output["effective_observation_summaries"] = summary_view(output)
            return output

    def quarantine_thought(self, review_id, memory_id, expected_revision, expected_meta_revision, reason):
        """Explicit evidence review; append exclusion, never erase the old thought.

        An assistant audit is not a model approval/rejection or a new experience.
        Its meta-version change invalidates decisions prepared with this memory.
        """
        text(reason)
        request = {"memory_id": memory_id, "expected_revision": expected_revision,
                   "expected_meta_revision": expected_meta_revision, "reason": reason}
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute('SELECT kind,body FROM (SELECT rowid,"id" AS "id","kind" AS "kind","body" AS "body" FROM life_evidence WHERE category=\'cognition\') AS life_cognition_artifacts WHERE id=?', (review_id,)).fetchone()
            if old:
                require(old[0] == "memory_quarantine" and json.loads(old[1])["request"] == request, "review id conflict")
                return json.loads(old[1])
            state, meta = self.store.read(db), self._meta(db)
            if state["revision"] != expected_revision or meta["revision"] != expected_meta_revision:
                raise Conflict("memory review inputs changed")
            cursor = db.execute("SELECT * FROM life_memories WHERE id=? AND kind='thought'", (memory_id,))
            row = cursor.fetchone(); require(row is not None, "unknown thought")
            original = dict(zip([c[0] for c in cursor.description], row))
            meta["revision"] += 1
            receipt = {"request": request, "memory_id": memory_id, "original_memory": original,
                "status": "excluded_from_future_retrieval", "source": "explicit_assistant_evidence_review_not_model_verdict",
                "at": self.clock.now().isoformat(), "meta_revision": meta["revision"]}
            db.execute("INSERT INTO life_evidence(category,id,kind,body) VALUES('cognition',?,?,?)", (review_id, "memory_quarantine", canonical(receipt)))
            self._save_meta(db, meta)
        return receipt

    def _decision_context(self, attempt_id):
        self.agenda.ensure()
        with self.store.connect() as db:
            self._decision_ready(db)
        context = self._snapshot()
        state = context["state"]
        context["unfinished_tasks"] = [a for a in state["activities"].values() if a["status"] in {"running", "interrupted"}]
        from .state_view import unfinished, progress_view, capabilities
        context["unfinished_matters"] = unfinished(state, self.p.config)
        context["activity_progress_facts"] = [progress_view(a, self.p.config) for a in state['activities'].values()]
        context["capabilities"] = capabilities(self.p.config)
        from .work_artifacts import public_task
        context["work_items"] = {k: {"definition": public_task(v), "actual_progress": state["work_items"][k],
            "seconds_until_deadline": (utc(v["deadline"])-utc(context["now"])).total_seconds()}
            for k, v in self.p.config.get("work_items", {}).items()}
        context["failed_attempts"] = [a for a in state["activities"].values() if a["status"] == "failed"]
        context["commitments"] = self.config["commitments"] + [c for c in state.get("commitments", []) if c["status"] == "confirmed"]
        context["commitments_source"] = self.config["commitments_source"]
        context["production_commitments"] = None
        from .daily_obligations import status as routine_status
        context["daily_obligations"] = routine_status(self.p.config, state, context["now"], self.calendar_provider)
        if self.p.config.get("mode") == "local_single_user":
            context["daily_agenda"] = self.agenda.view(context["now"], state=state)
            from .fine_plan import view as fine_view
            context['fine_agenda'] = fine_view(self, state)
        if self.p.config.get("planning_reference"):
            context["planning_reference"] = self.planning_reference(context["now"])
        from .retrieval_query import build_query
        context["retrieval_basis"],query=build_query(state,self.p.config,context["now"],commitments=context["commitments"],
            planning_reference=context.get("planning_reference"))
        if context.get("daily_agenda"):
            agenda_intents = [item for item in (context["daily_agenda"].get("current_item"),
                                               context["daily_agenda"].get("next_item")) if item]
            context["retrieval_basis"]["daily_agenda_intentions"] = [
                {"id": item["id"], "title": item["title"], "place": item["place"]} for item in agenda_intents]
            query += "\n当天计划意图（尚非经历）：" + "；".join(item["title"] for item in agenda_intents)
        context["memories"] = self.memory.retrieve(query, attempt_id + ":retrieve")
        with self.store.connect() as db:
            last = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","kind" AS "kind","body" AS "body" FROM life_evidence WHERE category=\'cognition\') AS life_cognition_artifacts WHERE kind=\'plan\' ORDER BY rowid DESC LIMIT 1').fetchone()
        context["existing_plan"] = json.loads(last[0]) if last else None
        from .skill_reading import public_books
        context["environment"] = {
            "places": self.p.config["places"], "objects": self.p.config["objects"],
            "books": public_books(self.p.config),
            "recipes": self.p.config["recipes"], "available_tools": state.get("available_tools", self.p.config["initial"]["available_tools"]),
            "movies": self.p.config.get('movies', {}),
            "household_world": self.p.config.get("household_world"),
        }
        # Capability facts, not generated candidates or a preselected response.
        context["execution_limits"] = {
            "movement_enabled": bool(self.p.config.get("household_world")),
            "current_place": state["place"],
            "objects_at_current_place": [key for key, obj in self.p.config["objects"].items()
                                         if obj["parent"] == state["place"]],
            "book_targets_at_current_place": [key for key, book in self.p.config["books"].items()
                if self.p.config["objects"][book["object"]]["parent"] == state["place"]],
            "recipe_targets_at_current_place": [key for key, recipe in self.p.config["recipes"].items()
                if self.p.config["objects"][recipe["tool"]]["parent"] == state["place"]],
            "existing_activity_operations": {a["id"]: (["continue"] if a["status"] == "running" else
                (["switch"] if state['active'] else ["resume"]) if a["status"] == "interrupted" else []) for a in state["activities"].values()},
            "new_activity_operations": ["switch"] if state['active'] else ["start"],
            "failed_attempt_rule": "failed/completed IDs are terminal; never resume them. New attempts may start only if current resources permit; shared reading progress is retained.",
        }
        if self.p.config.get("mode") == "local_single_user":
            context["movement_purpose_contract"] = {
                "source": "coarse_schedule_location_authority",
                "required_for": "always null; moving and serving actions are removed",
                "rule": "Coarse slots own transit and arrival. Rooms follow the current fine activity without movement checkpoints. Location alone never completes an activity.",
                "allowed": {},
            }
        start_targets = []; blocked_targets = []
        for kind, targets in (("reading", self.p.config["books"]), ("cooking", self.p.config["recipes"]),
                              ("watching", self.p.config.get('movies', {})),
                              ("work", self.p.config.get("work_items", {})), ("eating", state["meals"]), ("moving", self.p.config["places"]), ("serving", state["meals"]),
                              ("showering", {x["id"]: x for x in context.get("daily_obligations", []) if x["kind"] == "shower" and x["status"] == "due_flexible"})):
            for target in targets:
                action = {"operation": "start", "activity_id": None, "kind": kind, "target": target}
                try:
                    self._validate_action(action, state, self.clock.now())
                    start_targets.append({"kind": kind, "target": target})
                except (ValueError, KeyError) as exc:
                    blocked_targets.append({"kind": kind, "target": target, "reason": str(exc)})
        context["execution_limits"]["currently_startable_targets"] = start_targets
        context["execution_limits"]["blocked_targets"] = blocked_targets
        if self.p.config.get("household_world"):
            from .action_validation import constraints
            context["executor_constraints"] = constraints(self.p, state)
            with self.store.connect() as db:
                rejected = db.execute("SELECT id,context,receipt FROM life_cognition_runs WHERE kind='decision' AND status='rejected' ORDER BY rowid DESC LIMIT 3").fetchall()
                rejected_plans = {ident: row[0] for ident, _, _ in rejected
                    if (row := db.execute("SELECT response FROM life_model_calls WHERE id=?", (ident+":plan",)).fetchone()) and row[0]}
            context["validation_feedback"] = [{"attempt": ident, "error": json.loads(receipt),
                "rejected_plan_not_experience": json.loads(rejected_plans[ident]) if ident in rejected_plans else None,
                "role": "validator_feedback_not_world_experience"} for ident, raw, receipt in rejected
                if json.loads(raw)["state"]["revision"] == state["revision"]]
        context["current_state_evidence_id"] = "snapshot:" + str(state["revision"])
        context["evidence_precedence"] = "current snapshot and executable limits govern current facts; dated memories/thoughts and previous plans cannot override them"
        context["plan_horizon_seconds"] = self.config["plan_horizon_seconds"]
        context["near_window_seconds"] = self.config["near_window_seconds"]
        context["evidence_ids"] = ["snapshot:" + str(state["revision"]), "persona:" + context["persona"]["version"]]
        if context.get("daily_agenda"):
            context["evidence_ids"].append(context["daily_agenda"]["evidence_id"])
            context["evidence_ids"] += [item["id"] for item in context["daily_agenda"]["items"]]
        if context.get('fine_agenda'):
            context['evidence_ids'] += [b['id'] for plan in context['fine_agenda']['plans'] for b in plan['blocks']]
        # A supplied obligation is evidence of a requirement, never of completion.
        context["evidence_ids"] += [item["id"] for item in context["daily_obligations"]]
        if context.get("planning_reference"):
            context["evidence_ids"].append("planning-reference:" + context["planning_reference"]["version"])
        context["evidence_ids"] += [r["id"] for r in context["memories"]]
        context["evidence_ids"] += ["task:" + a["id"] for a in context["unfinished_tasks"]]
        context["evidence_ids"] += ["commitment:" + c["id"] for c in context["commitments"]]
        return context

    def planning_reference(self, now):
        if not self.p.config.get("planning_reference"):
            return None
        from .planning_reference import view as planning_reference_view
        return planning_reference_view(self.p.config["planning_reference"], self.p.config["places"], now,
                                       self.calendar_provider)

    def _validate_movement_purpose(self, purpose, state, target, at):
        """Validate declared intent without requiring a pre-existing object for every trip."""
        shape(purpose, {"kind", "reference_id"})
        kind, reference = purpose["kind"], purpose["reference_id"]
        require(kind in {"meal", "workday_duty", "pending_work", "reading", "cooking",
                         "shower", "housework", "work_skill", "general_study", "return_home", "resume_activity", "daily_agenda", "fine_agenda"},
                "unknown movement purpose")
        if kind in {'housework','work_skill'}:
            from .coarse_plan_execution import requirement
            required=requirement(self,state,at=at)
            require(required and required.get('mode')=='action' and required.get('kind')=='moving'
                and required.get('work' if kind=='work_skill' else 'housework',{}).get('id')==reference and required.get('destination')==target,
                'housework movement must match the current saved step')
            return
        if kind == 'fine_agenda':
            from .fine_plan import view
            item = next((b for plan in (view(self,state) or {}).get('plans',[]) for b in plan['blocks'] if b['id']==reference),None)
            require(item and item['place']==target and utc(item['end_at'])>utc(at), 'fine agenda movement target expired or mismatched')
            return
        if kind == "daily_agenda":
            agenda = self.agenda.view(at, state=state)
            item = agenda.get("current_item") if agenda else None
            destination = (item.get('destination') if item.get('kind') == 'commute' else item.get('place')) if item else None
            require(item and item["id"] == reference and destination == target,
                    "daily agenda purpose requires the current planned place or commute destination")
            return
        if kind == "general_study":
            require(target == "home.f2.study" and reference is None,
                    "general study purpose requires the confirmed study and no invented object")
            return
        if kind == "meal":
            meal = state.get("meals", {}).get(reference)
            require(meal and meal.get("place") == target and meal.get("remaining", 0) > 0,
                    "meal purpose lacks an available meal at the destination")
            return
        if kind == "pending_work":
            task = self.p.config.get("work_items", {}).get(reference)
            actual = state.get("work_items", {}).get(reference)
            require(task and actual and task.get("place") == target and actual.get("status") != "completed",
                    "pending-work purpose lacks a current work item at the destination")
            return
        if kind == "reading":
            book = self.p.config.get("books", {}).get(reference)
            obj = self.p.config.get("objects", {}).get(book.get("object"), {}) if book else {}
            require(book and obj.get("parent") == target, "reading purpose lacks content at the destination")
            return
        if kind == "cooking":
            recipe = self.p.config.get("recipes", {}).get(reference)
            obj = self.p.config.get("objects", {}).get(recipe.get("tool"), {}) if recipe else {}
            require(recipe and obj.get("parent") == target, "cooking purpose lacks its configured tool at the destination")
            return
        if kind == "shower":
            from .daily_obligations import status as routine_status
            due = {x["id"]: x for x in routine_status(
                self.p.config, state, at, self.calendar_provider)
                if x["kind"] == "shower" and x["status"] == "due_flexible"}
            require(reference in due and due[reference].get("place") == target,
                    "shower purpose lacks a due obligation at the destination")
            return
        if kind == "resume_activity":
            activity = state.get("activities", {}).get(reference)
            require(activity and activity.get("status") == "interrupted" and activity.get("place") == target,
                    "resume purpose lacks an interrupted activity at the destination")
            return
        from .daily_obligations import descendant
        if kind == "return_home":
            require(reference is None and not descendant(self.p.config, state["place"], "home")
                    and descendant(self.p.config, target, "home"), "return-home purpose/location mismatch")
            return
        reference_view = self.planning_reference(at)
        local = utc(at).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai"))
        end_hour, end_minute = map(int, reference_view["normal_end_window_local"]["until"].split(":"))
        end = local.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
        require(reference is None and target == reference_view["office"]["place_id"]
                and reference_view["computed"]["current_day"]["day_type"] == "workday"
                and local <= end, "workday-duty purpose is outside today's workday/office context")

    def _validate_action(self, action, state, at, *, fine_validated=False):
        shape(action, {"operation", "activity_id", "kind", "target"})
        from .coarse_plan_execution import validate
        validate(self, state, action, at=at)
        from .fine_plan import enforce_action
        if not fine_validated: enforce_action(self, state, action, at)
        from .daily_obligations import enforce_meal_action
        # In local life the saved agenda owns meal timing too. An old overdue
        # meal must not silently override a later user appointment or slot.
        if self.p.config.get('mode') != 'local_single_user' or self.agenda.read(at) is None:
            enforce_meal_action(self.p.config, state, at, action, self.calendar_provider)
        op, activity_id = action["operation"], action["activity_id"]
        require(op in {"start", "continue", "resume", "switch", "wait"}, "unsupported action/P3 capability")
        require(op != 'switch' or state['active'] is not None,
                'no active activity to switch: use resume for an interrupted activity, with null movement_purpose')
        trial = deepcopy(state)
        if op == "wait":
            require(activity_id is None and action["kind"] is None and action["target"] is None, "invalid wait")
            require(state["active"] is None, "wait requires no active activity; continue or explicitly interrupt first")
            return []
        if op in {"continue", "resume"} or (op == "switch" and activity_id is not None):
            require(activity_id in state["activities"], "unknown existing activity")
            a = state["activities"][activity_id]
            require((a["kind"], a["target"]) == (action["kind"], action["target"]), "existing activity identity mismatch")
            if op == "continue":
                require(state["active"] == activity_id and a["status"] == "running", "cannot continue activity")
                return []
        else:
            require(activity_id is None, "new activity must not supply existing id")
            # The current agenda owns movement. Historical trips to the same
            # destination must not veto a new route from the actual location.
            require(action['kind'] == 'moving' or not any(a["kind"] == action["kind"] and a["target"] == action["target"]
                            and a["status"] in {"running", "interrupted"} for a in state["activities"].values()),
                    "must continue/resume existing unfinished activity")
        operations = []
        if op == "switch":
            require(state["active"] is not None and state["active"] != activity_id, "nothing to switch")
            operations.append(("interrupt", {"activity_id": state["active"], "reason": "validated P2 choice"}))
        if op == "resume" or (op == "switch" and activity_id is not None):
            operations.append(("resume", {"activity_id": activity_id}))
        else:
            operations.append(("start", {"activity_id": "p2-trial-new", "kind": action["kind"], "target": action["target"]}))
        for operation, payload in operations:
            self.p._transition(trial, operation, payload, at)
        return operations

    def decide(self, attempt_id):
        with self.store.connect() as db:
            old = db.execute("SELECT kind,status,receipt FROM life_cognition_runs WHERE id=?", (attempt_id,)).fetchone()
        if old and old[1] == "committed":
            require(old[0] == "decision", "P2 run id reused")
            return json.loads(old[2])
        require(self.p.snapshot().get("sleep", {}).get("status") != "sleeping", "P3 sleeping; wake before choosing life actions")
        self.synchronize(attempt_id + ":ingest")
        reflection = self.optional_reflect(attempt_id + ":reflection")
        context, done = self._prepare(attempt_id, "decision", lambda: self._decision_context(attempt_id))
        if done:
            return done
        try:
            plan = self.calls.ask(attempt_id + ":plan", "plan", context)
            shape(plan, {"items"})
            require(isinstance(plan["items"], list) and 1 <= len(plan["items"]) <= 6, "invalid coarse plan")
            end = 0
            item_ids = set()
            for item in plan["items"]:
                fields = {"id", "goal", "start_after_seconds", "duration_seconds", "evidence_ids"}
                if context.get("executor_constraints"): fields.add("execution")
                if "additional_actions" in item: fields.add("additional_actions")
                if context.get("movement_purpose_contract"): fields.add("movement_purpose")
                shape(item, fields)
                text(item["id"]); text(item["goal"]); refs(item["evidence_ids"], context["evidence_ids"])
                require(context["current_state_evidence_id"] in item["evidence_ids"], "plan must cite current snapshot")
                require(item["id"] not in item_ids, "duplicate plan item")
                item_ids.add(item["id"])
                if item is plan['items'][0] and context.get('executor_constraints'):
                    op = item['execution']['operation']
                    require(op != 'switch' or context['state']['active'] is not None,
                            'no active activity to switch: resume the existing interrupted activity with null movement_purpose')
                if context.get("movement_purpose_contract"):
                    moving = item["execution"]["kind"] == "moving" and item["execution"]["operation"] in {"start", "switch"} and item['execution']['activity_id'] is None
                    require(moving == (item["movement_purpose"] is not None),
                            "movement purpose is required only for a new moving activity")
                    if moving:
                        self._validate_movement_purpose(item["movement_purpose"], context["state"],
                                                        item["execution"]["target"], utc(context["now"]))
            if context.get("executor_constraints"):
                from .action_validation import validate_plan
                fine = (context.get('fine_agenda') or {}).get('current_item')
                immediate = plan['items'][0]['execution']
                if fine and immediate['kind'] in {'reading','watching','work'}:
                    require((immediate['kind'],immediate['target'])==(fine['kind'],fine['target']),
                            'resource choice differs from saved fine schedule; follow current block or replan')
                feasibility = validate_plan(self, plan, context)
                with self.store.connect() as db:
                    db.execute("INSERT INTO life_evidence(category,id,kind,body) VALUES('cognition',?, 'plan_feasibility', ?)", (attempt_id+":feasibility", canonical(feasibility)))
            for index, item in enumerate(plan["items"]):
                route_owned = bool(context.get("executor_constraints") and index == 0 and feasibility[0]["route_check"])
                require(type(item["start_after_seconds"]) is int and type(item["duration_seconds"]) is int
                        and item["start_after_seconds"] >= end and item["duration_seconds"] >= (0 if route_owned else 1), "invalid plan window")
                end = item["start_after_seconds"] + item["duration_seconds"]
                require(end <= self.config["plan_horizon_seconds"], "plan exceeds horizon")
            require(plan["items"][0]["start_after_seconds"] <= self.config["near_window_seconds"], "no near-term plan item")
            plan_context = {**context, "plan": plan, "near_item": plan["items"][0]}
            if context.get("executor_constraints"):
                plan_context["near_executor_check"] = feasibility[0]
                plan_context["plan_item_checks"] = feasibility
                plan_context["plan_boundary"] = "Only item 0 can be selected now. Later items are tentative intentions, not projected successes; no automatic execution. Re-evaluate after actual checkpoint outcome."
            route_owned = bool(plan_context.get("near_executor_check", {}).get("route_check"))
            if route_owned:
                from .action_validation import executor_decomposition
                decomp = executor_decomposition(self.p, plan["items"][0], feasibility[0])
                plan_context["decomposition_source"] = "project_executor_route_arithmetic_not_model_choice_or_actual_result"
                with self.store.connect() as db:
                    db.execute("INSERT INTO life_evidence(category,id,kind,body) VALUES('cognition',?, 'executor_decomposition', ?)",
                               (attempt_id+":executor-decomposition", canonical({"source": plan_context["decomposition_source"], "body": decomp})))
            else:
                decomp = self.calls.ask(attempt_id + ":decompose", "decompose", plan_context)
            shape(decomp, {"plan_item_id", "steps"})
            require(decomp["plan_item_id"] == plan["items"][0]["id"], "decomposition must be near-term")
            require(isinstance(decomp["steps"], list) and 1 <= len(decomp["steps"])
                    and (route_owned or len(decomp["steps"]) <= 6), "invalid decomposition")
            for step in decomp["steps"]:
                step_fields = {"intent", "duration_seconds", "evidence_ids"}
                if plan_context.get("near_executor_check", {}).get("route_check"): step_fields.add("route_span")
                shape(step, step_fields)
                text(step["intent"]); refs(step["evidence_ids"], context["evidence_ids"])
                require(type(step["duration_seconds"]) is int and step["duration_seconds"] >= (0 if route_owned else 1), "invalid step time")
            require(sum(s["duration_seconds"] for s in decomp["steps"]) <= plan["items"][0]["duration_seconds"], "decomposition exceeds plan item")
            if context.get("executor_constraints"):
                require(sum(s["duration_seconds"] for s in decomp["steps"]) >= feasibility[0]["minimum_seconds"], "decomposition shorter than executor minimum")
                from .action_validation import validate_decomposition
                validate_decomposition(decomp, feasibility[0])
            self._guard(attempt_id + ":plan-guard", "plan_and_decomposition", plan_context, {"plan": plan, "decomposition": decomp})
            action_context = {**plan_context, "decomposition": decomp}
            proposed = self.calls.ask(attempt_id + ":candidates", "candidates", action_context)
            shape(proposed, {"candidates"})
            require(isinstance(proposed["candidates"], list) and 1 <= len(proposed["candidates"]) <= 4, "invalid candidates")
            valid, invalid, ids = [], [], set()
            for candidate in proposed["candidates"]:
                try:
                    fields = {"id", "description", "action", "evidence_ids"}
                    if context.get("movement_purpose_contract"): fields.add("movement_purpose")
                    shape(candidate, fields)
                    text(candidate["id"]); text(candidate["description"])
                    refs(candidate["evidence_ids"], context["evidence_ids"])
                    require(context["current_state_evidence_id"] in candidate["evidence_ids"], "candidate must cite current snapshot")
                    require(candidate["id"] not in ids, "duplicate candidate id")
                    ids.add(candidate["id"])
                    if context.get("movement_purpose_contract"):
                        moving = candidate["action"]["kind"] == "moving" and candidate["action"]["operation"] in {"start", "switch"} and candidate['action']['activity_id'] is None
                        require(moving == (candidate["movement_purpose"] is not None),
                                "movement purpose is required only for a new moving activity")
                        if moving:
                            self._validate_movement_purpose(candidate["movement_purpose"], context["state"],
                                                            candidate["action"]["target"], utc(context["now"]))
                    self._validate_action(candidate["action"], context["state"], utc(context["now"]))
                    valid.append(candidate)
                except (ValueError, TypeError, KeyError) as exc:
                    invalid.append({"candidate": candidate, "error": str(exc)})
            with self.store.connect() as db:
                db.execute("INSERT OR IGNORE INTO life_evidence(category,id,kind,body) VALUES('cognition',?,'candidate_validation',?)",
                           (attempt_id + ":candidate-validation", canonical({"accepted": valid, "rejected": invalid})))
            require(bool(valid), "no valid model candidate; no fixed fallback")
            if context["state"]["active"]:
                require(any(c["action"]["operation"] == "continue" for c in valid), "model omitted continue-current option")
            predict_context = {**action_context, "candidates": valid}
            predictions = self.calls.ask(attempt_id + ":predict", "predict", predict_context)
            shape(predictions, {"forecasts"})
            require(isinstance(predictions["forecasts"], list), "invalid forecasts")
            require(len(predictions["forecasts"]) == len(valid) and
                    {f["candidate_id"] for f in predictions["forecasts"]} == {c["id"] for c in valid}, "forecast/candidate mismatch")
            for forecast in predictions["forecasts"]:
                shape(forecast, {"candidate_id", "summary", "evidence_ids"})
                text(forecast["summary"]); refs(forecast["evidence_ids"], context["evidence_ids"])
            select_context = {**predict_context, "predictions": predictions}
            selection = self.calls.ask(attempt_id + ":select", "select", select_context)
            shape(selection, {"candidate_id", "summary", "evidence_ids"})
            text(selection["summary"]); refs(selection["evidence_ids"], context["evidence_ids"])
            require(context["current_state_evidence_id"] in selection["evidence_ids"], "selection must cite current snapshot")
            chosen = next((c for c in valid if c["id"] == selection["candidate_id"]), None)
            require(chosen is not None, "selection not among validated candidates")
            if context.get("executor_constraints"):
                planned = {k: v for k, v in plan["items"][0]["execution"].items() if k != "scope"}
                require(chosen["action"] == planned, "choice differs from validated near plan; explicitly replan")
                if context.get("movement_purpose_contract"):
                    require(chosen["movement_purpose"] == plan["items"][0]["movement_purpose"],
                            "choice movement purpose differs from validated near plan")
            if context["memories"]:
                require(set(selection["evidence_ids"]) & {m["id"] for m in context["memories"]}, "selection did not cite retrieved memory")
            self._guard(attempt_id + ":choice-guard", "selected_action", select_context,
                        {"selection": selection, "candidate": chosen})
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                already = db.execute("SELECT receipt FROM life_cognition_runs WHERE id=? AND status='committed'", (attempt_id,)).fetchone()
                if already:
                    return json.loads(already[0])
                state, meta = self._fresh(db, context)
                self._decision_ready(db)
                fine = (context.get('fine_agenda') or {}).get('current_item')
                if fine and chosen['action']['kind'] in {'reading','watching','work'}:
                    from .fine_plan import validate_commit
                    validate_commit(self, db, context, state, chosen['action'], self.clock.now())
                operations = self._validate_action(chosen["action"], state, self.clock.now(),
                                                  fine_validated=bool(fine))
                event_receipts = []
                for index, (operation, payload) in enumerate(operations):
                    if operation == "start":
                        payload["activity_id"] = "activity:" + attempt_id
                    current = self.store.read(db)
                    event_receipts.append(self.p._commit_locked(db, "p2:" + attempt_id + ":" + str(index),
                        {"operation": operation, "payload": payload, "expected_revision": current["revision"]}, None))
                for kind, body in (("plan", plan), ("decomposition", decomp), ("forecast", predictions), ("selection", selection)):
                    db.execute("INSERT INTO life_evidence(category,id,kind,body) VALUES('cognition',?,?,?)", (attempt_id + ":" + kind, kind, canonical(body)))
                final = self.store.read(db)
                from .fine_plan import bind
                bind(db, context, final)
                receipt = {"attempt_id": attempt_id, "selected": chosen, "selection": selection,
                           "input_revision": context["state"]["revision"], "state_revision": final["revision"],
                           "active_activity": final["active"], "events": event_receipts, "model_kind": self.calls.model.kind,
                           "at": self.clock.now().isoformat(), "optional_reflection": reflection}
                if context.get("daily_agenda"):
                    agenda_item = context["daily_agenda"].get("current_item")
                    receipt["daily_agenda_basis"] = {
                        "evidence_id": context["daily_agenda"]["evidence_id"],
                        "item_id": agenda_item["id"] if agenda_item else None,
                        "role": "coarse_intention_refined_by_this_decision_not_actual_result"}
                if context.get("executor_constraints") and final["active"]:
                    current = final["activities"][final["active"]]
                    receipt["execution_boundary"] = {"activity_id": current["id"], "progress": current["progress"],
                        "scope": plan["items"][0]["execution"]["scope"], "decision_id": attempt_id}
                self._finish(db, attempt_id, receipt)
            return receipt
        except Exception as exc:
            self._reject(attempt_id, exc)
            raise

    def read_checkpoint(self, attempt_id):
        """Model processes real supplied text only after the P1 checkpoint is due."""
        from .skill_reading import heartbeat
        if heartbeat(self):
            return {'status': 'simulated_reading', 'model_called': False}
        with self.store.connect() as db:
            old = db.execute("SELECT kind,status,receipt FROM life_cognition_runs WHERE id=?", (attempt_id,)).fetchone()
        if old and old[1] == "committed":
            require(old[0] == "reading", "P2 run id reused")
            return json.loads(old[2])
        def build():
            context = self._snapshot()
            state = context["state"]
            require(state["active"] is not None, "no active reading")
            a = state["activities"][state["active"]]
            require(a["kind"] == "reading" and a["status"] == "running", "not reading")
            require(utc(a["next_due_at"]) <= self.clock.now(), "reading checkpoint not due")
            book = self.p.config["books"][a["target"]]
            from .reading_evidence import reading_window
            content, previous, window = reading_window(a["target"], book, a["progress"],
                1000 if book.get('source')=='local_library' else self.config["reading_chunk_chars"])
            context['reading_source_mode'] = book.get('reading_mode','full_text')
            context["activity_id"] = a["id"]
            context.update(content=content, reading_context=previous, reading_window=window,
                           reading_contract="sentence-v2: only content[start:end] advances progress; previous context has zero credit")
            return context
        context, done = self._prepare(attempt_id, "reading", build)
        if done:
            return done
        try:
            output = self.calls.ask(attempt_id + ":read", "read", context)
            from .reading_evidence import validate_read
            aligned = validate_read(output, context)
            self._guard(attempt_id + ":guard", "read_content", aligned, output)
            evidence = {k: v for k, v in context["content"].items() if k != "id"}
            evidence.update(source="model_reading", note=output["note"], model_call_id=attempt_id + ":read")
            # P1 captures a checkpoint in stage_result and retains conflicts for explicit review.
            self.p.stage_result(attempt_id + ":result", context["state"]["revision"], context["activity_id"],
                                evidence, context["now"])
            receipt = self.p.settle(attempt_id + ":result")
            with self.store.connect() as db:
                self._finish(db, attempt_id, receipt)
            return receipt
        except Exception as exc:
            self._reject(attempt_id, exc)
            raise
