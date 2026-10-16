"""Isolated P3 messages/sleep. All timing/transactions are project adaptations.

Messages are test envelopes, not deliveries. No scheduler, LMC, production or
transport imports. Sleep credits cover elapsed intervals only, exactly once.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from .clock import TestClock, utc
from .config import canonical
from .activity_engine import require
from .store import Conflict
from .cognition_contracts import refs, shape, text

LOCAL = timezone(timedelta(hours=8), "Asia/Shanghai")
NORMAL_NIGHT_START_MINUTE = 18 * 60
LOCAL_DAY_BOUNDARY_MINUTE = 4 * 60


def _hour_number(value: str) -> int | None:
    if value.isdigit():
        hour = int(value)
        return hour if 0 <= hour <= 23 else None
    values = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
              '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
              '十一': 11, '十二': 12}
    return values.get(value)


def settings():
    return json.loads(Path(__file__).with_name("interaction_config.json").read_text(encoding="utf8"))


def validate(config):
    source = config["source"]
    require(source in {"test_fixture", "user_confirmed_local_single_user"} and config["timezone"] == "Asia/Shanghai", "P3 source/timezone required")
    require(config["wake_minutes"] == {"workday": 420, "swimming": 390, "weekend": 450}, "confirmed wake references differ")
    require(type(config["wake_jitter_minutes"]) is int and -5 <= config["wake_jitter_minutes"] <= 5, "wake jitter outside confirmed range")
    require(all(config[key] is None for key in ("special_schedule_policy", "late_sleep_policy", "offline_sleep_policy")), "special/offline rules remain unconfigured")
    expected_recognition = ("explicit_test_envelope_not_production_classifier" if source == "test_fixture"
                            else "host_explicit_intent_single_reply_path")
    require(config["goodnight_recognition"] == expected_recognition, "unsupported intent classifier")
    previous_end = None
    for window in sorted(config["normal_sleep_windows"], key=lambda w: utc(w["from"])):
        shape(window, {"from", "until", "wake_date", "source"})
        require(window["source"] == ("test_fixture" if source == "test_fixture" else "user_confirmed"), "bedtime window provenance mismatch")
        start, end = utc(window["from"]), utc(window["until"])
        require(start < end and (previous_end is None or previous_end <= start), "invalid/overlapping normal sleep windows")
        previous_end = end
        datetime.strptime(window["wake_date"], "%Y-%m-%d")
    for day, info in config["calendar"].items():
        datetime.strptime(day, "%Y-%m-%d")
        shape(info, {"day_type", "source"})
        require(info["day_type"] in {"workday", "weekend", "special"} and info["source"] == ("test_fixture" if source == "test_fixture" else "user_confirmed"), "invalid calendar provenance")


class Interaction:
    def __init__(self, cognition, config=None):
        self.cog, self.p = cognition, cognition.p
        self.store, self.clock = self.p.store, self.p.clock
        from .state_schema import facts_only
        self.config = facts_only(deepcopy(config) if config is not None else settings())
        validate(self.config)
        with self.store.connect() as db:
            db.executescript('\n                CREATE TABLE IF NOT EXISTS life_received_messages(id TEXT PRIMARY KEY,request TEXT NOT NULL,receipt TEXT NOT NULL);\n                CREATE TABLE IF NOT EXISTS life_interaction_replies(message_id TEXT PRIMARY KEY,attempt_id TEXT UNIQUE NOT NULL,body TEXT NOT NULL)')
            db.execute("BEGIN IMMEDIATE")
            old = db.execute('SELECT config FROM (SELECT rowid,"id" AS "id","body" AS "config" FROM life_state WHERE name=\'interaction\') AS life_interaction_config WHERE id=1').fetchone()
            if old:
                require(facts_only(json.loads(old[0])) == self.config, "P3 config changed; use another run")
                db.execute("UPDATE life_state SET body=? WHERE name='interaction'",(canonical(self.config),))
            else:
                state = self.store.read(db)
                require(state.get("cognition_enabled"), "P2 required")
                state["sleep"] = {"status": "awake", "current": None, "episodes": [], "total_seconds": 0,
                    "last_wake": None, "awaiting_goodnight": True}
                state["commitments"] = []
                state["revision"] += 1
                db.execute("UPDATE life_state SET body=?  WHERE name='current' AND ( id=1)", (canonical(state),))
                db.execute("INSERT INTO life_state(name,id,body) VALUES('interaction',1,?)", (canonical(self.config),))

    def _event(self, db, state, event_id, kind, fact, at):
        """Use the existing P1 ledger; P2 ingests these observations in ledger order."""
        state["revision"] += 1
        state["as_of"] = max(utc(state["as_of"]), at).isoformat()
        production = self.p.config.get("mode") == "local_single_user"
        observation = {"type": kind, "fact": fact, "occurred_at": at.isoformat(),
                       "knowledge_basis":
                       "committed_local_life_event" if production else "isolated_p3_committed_self_event"}
        request = {"operation": "p3", "observation": observation}
        receipt = {"event_id": event_id, "revision": state["revision"], "occurred_at": at.isoformat(),
                   "recorded_at": self.clock.now().isoformat(), "source":
                   "local_life_message_or_elapsed_sleep" if production else "p3_test_envelope_or_elapsed_sleep"}
        from .event_store import append
        append(db, event_id, request, receipt, state, self.p.config)
        db.execute("UPDATE life_state SET body=?  WHERE name='current' AND ( id=1)", (canonical(state),))
        return receipt

    @staticmethod
    def _episode(state):
        return next(e for e in state["sleep"]["episodes"] if e["id"] == state["sleep"]["current"])

    def _advance(self, db, state, prefix, now):
        require(now >= utc(state["as_of"]), "clock moved backwards")
        if state["sleep"]["status"] != "sleeping":
            return None
        episode = self._episode(state)
        due = utc(episode["natural_wake_at"]) if episode["natural_wake_at"] else None
        end = min(now, due) if due else now
        start = utc(episode["settled_until"])
        elapsed = (end-start).total_seconds()
        # Real-clock offline continuity remains unspecified. Do not silently backfill.
        if not isinstance(self.clock, TestClock) and elapsed > self.p.config["max_gap_seconds"]:
            raise Conflict("offline sleep continuity unconfigured; no automatic backfill")
        if elapsed > 0:
            sleep = state["sleep"]
            sleep["total_seconds"] = round(sleep["total_seconds"]+elapsed, 6)
            episode["seconds"] = round(episode["seconds"]+elapsed, 6)
            episode["settled_until"] = end.isoformat()
            self._event(db, state, prefix+":sleep-progress", "sleep_progress", {
                "episode_id": episode["id"], "from": start.isoformat(), "to": end.isoformat(),
                "elapsed_seconds": elapsed, "total_seconds": sleep["total_seconds"],
                "continuity": "test_clock_fixture" if isinstance(self.clock, TestClock) else "bounded_real_clock_interval"}, end)
        if due and now >= due:
            self._wake(db, state, prefix+":natural-wake", due, "natural", None)
            return "natural"
        return None

    def _wake(self, db, state, event_id, at, reason, message_id):
        episode = self._episode(state)
        episode.update(ended_at=at.isoformat(), wake_reason=reason, wake_message_id=message_id)
        wake = {"episode_id": episode["id"], "reason": reason, "message_id": message_id,
                "at": at.isoformat(), "episode_seconds": episode["seconds"],
                "total_seconds": state["sleep"]["total_seconds"]}
        state["sleep"].update(status="awake", current=None, last_wake=wake,
                              awaiting_goodnight=True, pending_goodnight=None)
        self._event(db, state, event_id, "wake", wake, at)

    def _start_sleep(self, db, state, prefix, now, message_id, *, trigger="goodnight"):
        schedule = self._schedule(state, now)
        if trigger == 'quiet_night_fallback':
            schedule['reason'] = 'quiet_night_fallback_with_confirmed_natural_wake_reference'
        episode = {"id": prefix+":sleep", "started_at": now.isoformat(), "settled_until": now.isoformat(),
                   "seconds": 0, "ended_at": None, "wake_reason": None, "wake_message_id": None,
                   "start_message_id": message_id, "sleep_trigger": trigger, "place": state["place"], **schedule}
        state["sleep"]["episodes"].append(episode)
        state["sleep"].update(status="sleeping", current=episode["id"], awaiting_goodnight=False,
                              pending_goodnight=None)
        self._event(db, state, prefix+":sleep-start", "sleep_start", deepcopy(episode), now)
        return schedule["schedule_status"]

    def start_pending_sleep_if_ready(self):
        """Start accepted sleep after the remaining bedtime routine completes."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self.store.read(db)
            pending = state.get("sleep", {}).get("pending_goodnight")
            if not pending or state["sleep"]["status"] != "awake" or state.get("active"):
                return None
            from .daily_obligations import unresolved_before_sleep
            if unresolved_before_sleep(
                    self.p.config, state, self.clock.now(),
                    getattr(self.cog, "calendar_provider", None)):
                return None
            prefix = "p3:deferred-goodnight:" + pending["message_id"]
            status = self._start_sleep(db, state, prefix, self.clock.now(), pending["message_id"])
            return {"sleep_request": status, "sleep": deepcopy(state["sleep"])}

    def start_fallback_sleep_if_ready(self):
        """Host-owned quiet-night fallback; never infer that the user is asleep."""
        if self.p.config.get("mode") != "local_single_user":
            return None
        now = self.clock.now()
        local = utc(now).astimezone(LOCAL)
        if not 2 <= local.hour < 4:
            return None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self.store.read(db)
            sleep = state.get("sleep", {})
            if sleep.get("status") != "awake" or state.get("active") or sleep.get("pending_goodnight"):
                return None
            from .daily_obligations import descendant, unresolved_before_sleep
            if not descendant(self.p.config, state["place"], "home"):
                return None
            if unresolved_before_sleep(self.p.config, state, now,
                                       getattr(self.cog, "calendar_provider", None)):
                return None
            # Include queued deliveries, which have not reached receive() yet.
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'life_agent_inbox' in tables and db.execute(
                    "SELECT 1 FROM life_agent_inbox WHERE status='pending' LIMIT 1").fetchone():
                return None
            contacts = []
            for request, receipt in db.execute("SELECT request,receipt FROM life_received_messages"):
                request, receipt = json.loads(request), json.loads(receipt)
                at = request.get('received_at') or receipt.get('occurred_at')
                if at:
                    contacts.append(utc(at))
            if sleep.get('last_wake'):
                contacts.append(utc(sleep['last_wake']['at']))
            if contacts and now - max(contacts) < timedelta(minutes=30):
                return None
            schedule = self._schedule(state, now)
            if not schedule.get('natural_wake_at'):
                return None
            notice = getattr(self, 'before_fallback_sleep', None)
            if notice is not None:
                notice(local.date().isoformat())
            prefix = 'p3:quiet-night:' + now.isoformat()
            self._start_sleep(db, state, prefix, now, None, trigger='quiet_night_fallback')
            return {"sleep_request": "quiet_night_fallback", "sleep": deepcopy(state['sleep'])}

    def _schedule(self, state, now):
        if self.config["source"] == "user_confirmed_local_single_user" and not self.config["normal_sleep_windows"]:
            return self._formal_normal_schedule(state, now)
        window = next((w for w in self.config["normal_sleep_windows"] if utc(w["from"]) <= now < utc(w["until"])), None)
        if window is None:
            return {"natural_wake_at": None, "schedule_status": "unconfigured", "reason": "bedtime_or_special_schedule_unconfigured"}
        day = window["wake_date"]
        info = self.config["calendar"].get(day)
        if not info or info["day_type"] == "special":
            return {"natural_wake_at": None, "schedule_status": "unconfigured", "reason": "calendar_or_special_work_unconfigured"}
        swimming = [c for c in state["commitments"] if c["status"] == "confirmed" and c["activity"] == "morning_swim"
                    and utc(c["due_at"]).astimezone(LOCAL).date().isoformat() == day]
        branch = "weekend" if info["day_type"] == "weekend" else "swimming" if swimming else "workday"
        due = datetime.fromisoformat(day).replace(tzinfo=LOCAL) + timedelta(
            minutes=self.config["wake_minutes"][branch]+self.config["wake_jitter_minutes"])
        if utc(due) <= now:
            return {"natural_wake_at": None, "schedule_status": "unconfigured", "reason": "wake_time_already_passed_no_next_day_rollover"}
        return {"natural_wake_at": utc(due).isoformat(), "schedule_status": "configured_test_window",
                "branch": branch, "wake_date": day, "source": self.config["wake_source"],
                "morning_swim_evidence": [c["source_message"] for c in swimming] if branch == "swimming" else [],
                "jitter_minutes": self.config["wake_jitter_minutes"], "bedtime_window_source": "test_fixture"}

    def _formal_normal_schedule(self, state, now):
        """Resolve a confirmed ordinary night without reviving a day template.

        Goodnight still starts sleep.  This adapter only selects the already
        confirmed natural-wake branch from the App work/rest calendar.  Daytime
        sleep and the near-wake 04:00+ interval remain explicit exceptions.
        """
        local = utc(now).astimezone(LOCAL)
        minute = local.hour * 60 + local.minute
        if minute >= NORMAL_NIGHT_START_MINUTE:
            wake_day = local.date() + timedelta(days=1)
        elif minute < LOCAL_DAY_BOUNDARY_MINUTE:
            wake_day = local.date()
        else:
            return {"natural_wake_at": None, "schedule_status": "unconfigured",
                    "reason": "daytime_or_near_wake_sleep_requires_explicit_policy"}
        provider = getattr(self.cog, "calendar_provider", None)
        row = provider(wake_day.isoformat()) if provider else None
        if row is not None:
            require(row.get("date") == wake_day.isoformat(), "sleep work calendar date mismatch")
            require(row.get("day_type") in {"workday", "rest_day"}, "invalid sleep work calendar day type")
            day_type = row["day_type"]
            calendar_source = "app.work_calendar"
        else:
            day_type = "workday" if wake_day.weekday() < 5 else "rest_day"
            calendar_source = "weekday_fallback_unrecorded"
        swimming = [c for c in state["commitments"] if c["status"] == "confirmed"
                    and c["activity"] == "morning_swim"
                    and utc(c["due_at"]).astimezone(LOCAL).date() == wake_day]
        branch = "weekend" if day_type == "rest_day" else "swimming" if swimming else "workday"
        due = datetime.combine(wake_day, datetime.min.time(), tzinfo=LOCAL) + timedelta(
            minutes=self.config["wake_minutes"][branch] + self.config["wake_jitter_minutes"])
        explicit = self._explicit_wake_time(wake_day, now)
        if explicit is not None:
            due, source_message = explicit
            branch = 'explicit_user_wake'
        require(utc(due) > utc(now), "ordinary night wake must follow goodnight")
        result = {"natural_wake_at": utc(due).isoformat(),
                "schedule_status": "configured_user_confirmed_normal_night",
                "reason": "goodnight_triggered_sleep_with_confirmed_natural_wake_reference",
                "branch": branch, "wake_date": wake_day.isoformat(),
                "source": self.config["wake_source"],
                "calendar_source": calendar_source,
                "morning_swim_evidence": [c["source_message"] for c in swimming] if branch == "swimming" else [],
                "jitter_minutes": self.config["wake_jitter_minutes"],
                "night_boundary_source": "project_adaptation_local_day_boundary_not_D2A"}
        if explicit is not None:
            result.update(source='explicit user wake time', wake_source_message=source_message)
        return result

    def _explicit_wake_time(self, wake_day, bedtime):
        pattern = re.compile(r'([0-2]?\d|十一|十二|十|[一二两三四五六七八九])点(半)?[^。！？!?]{0,8}起床')
        with self.store.connect() as db:
            rows = db.execute('SELECT id,request FROM life_received_messages ORDER BY rowid DESC LIMIT 40').fetchall()
        for message_id, raw in rows:
            try:
                content = json.loads(raw).get('content', '')
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            match = pattern.search(content)
            if not match:
                continue
            hour = _hour_number(match.group(1))
            if hour is None:
                continue
            due = datetime.combine(wake_day, datetime.min.time(), tzinfo=LOCAL) + timedelta(
                hours=hour, minutes=30 if match.group(2) else 0)
            if utc(due) > utc(bedtime):
                return due, message_id
        return None

    def repair_missing_normal_wake(self):
        """Append an idempotent correction for the former formal-sleep bug."""
        if self.config["source"] != "user_confirmed_local_single_user":
            return None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self.store.read(db)
            if state.get("sleep", {}).get("status") != "sleeping":
                return None
            episode = self._episode(state)
            correction_id = "p3:normal-wake-correction:" + episode["id"]
            prior = db.execute('SELECT receipt FROM (SELECT rowid,"id" AS "id","request" AS "request","receipt" AS "receipt" FROM life_receipts WHERE category=\'sleep_tick\') AS life_sleep_ticks WHERE id=?', (correction_id,)).fetchone()
            if prior:
                return json.loads(prior[0])
            if episode.get("natural_wake_at"):
                return None
            schedule = self._formal_normal_schedule(state, utc(episode["started_at"]))
            if not schedule.get("natural_wake_at"):
                return None
            due, now = utc(schedule["natural_wake_at"]), self.clock.now()
            old = {key: episode.get(key) for key in (
                "natural_wake_at", "schedule_status", "reason", "seconds", "settled_until")}
            episode.update(schedule)
            invalid_events = []
            for event_id, raw in db.execute("SELECT id,request FROM (SELECT rowid,id,request,receipt FROM life_receipts WHERE category='event_control') ORDER BY rowid"):
                request = json.loads(raw)
                observation = request.get("observation", {}) if request.get("operation") == "p3" else {}
                fact = observation.get("fact", {})
                if (observation.get("type") == "sleep_progress"
                        and fact.get("episode_id") == episode["id"]
                        and utc(fact["to"]) > due):
                    invalid_events.append(event_id)
                    quarantine = {"memory_id": "mem:" + event_id,
                                  "reason": "sleep interval exceeded corrected natural wake boundary",
                                  "correction_id": correction_id, "source_event": event_id}
                    db.execute("INSERT OR IGNORE INTO life_evidence(category,id,kind,body) VALUES('cognition',?, 'memory_quarantine', ?)",
                               (correction_id + ":quarantine:" + event_id, canonical(quarantine)))
            if utc(episode["settled_until"]) > due:
                corrected_seconds = max(0.0, (due - utc(episode["started_at"])).total_seconds())
                excess = max(0.0, float(episode["seconds"]) - corrected_seconds)
                require(self.config["sleep_seconds_per_point"] is None,
                        "numeric sleep recovery requires a separate compensating correction")
                episode["seconds"] = round(corrected_seconds, 6)
                episode["settled_until"] = due.isoformat()
                state["sleep"]["total_seconds"] = round(
                    max(0.0, float(state["sleep"]["total_seconds"]) - excess), 6)
            fact = {"episode_id": episode["id"], "original": old,
                    "corrected_natural_wake_at": due.isoformat(),
                    "corrected_episode_seconds": episode["seconds"],
                    "invalid_sleep_progress_events": invalid_events,
                    "effect": "state correction only; no post-wake activity or user action generated",
                    "source": "confirmed_goodnight_and_natural_wake_rule_code_fix"}
            correction = self._event(db, state, correction_id + ":event",
                                     "sleep_schedule_correction", fact, now)
            if now >= due:
                self._wake(db, state, correction_id + ":natural-wake", due, "natural", None)
            receipt = {"correction_id": correction_id, "episode_id": episode["id"],
                       "natural_wake_at": due.isoformat(), "applied_at": now.isoformat(),
                       "woke_now": now >= due, "invalid_events": invalid_events,
                       "state_revision": state["revision"], "event_receipt": correction}
            db.execute("INSERT INTO life_receipts(category,id,request,receipt) VALUES('sleep_tick',?,?,?)",
                       (correction_id, canonical({"operation": "repair_missing_normal_wake"}), canonical(receipt)))
            has_scheduler = db.execute(
                "SELECT 1 FROM life_state WHERE name='scheduler'"
            ).fetchone()
            row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_state WHERE name=\'scheduler\') AS life_scheduler_state WHERE id=1').fetchone() if has_scheduler else None
            if row:
                meta = json.loads(row[0]); meta.update(dirty=True, next_decision=now.isoformat())
                db.execute("UPDATE life_state SET body=?  WHERE name='scheduler' AND ( id=1)", (canonical(meta),))
            return receipt

    def _commitment(self, state, change, message_id, content):
        if change is None:
            return
        shape(change, {"id", "operation", "description", "evidence_quote", "due_at", "activity"})
        for key in ("id", "description", "evidence_quote"):
            require(isinstance(change[key], str) and bool(change[key].strip()), "invalid commitment field")
        require(change["evidence_quote"] in content and change["description"] in content, "commitment lacks explicit message evidence")
        require(change["operation"] in {"confirm", "cancel"} and change["activity"] in {"morning_swim", "other"}, "invalid commitment change")
        utc(change["due_at"])
        old = next((c for c in state["commitments"] if c["id"] == change["id"]), None)
        require(not any(c["id"] == change["id"] for c in self.cog.config["commitments"]), "commitment id already used by P2 fixture")
        if change["operation"] == "cancel":
            require(old is not None and old["status"] == "confirmed", "no confirmed commitment to cancel")
        if old:
            state["commitments"].remove(old)
        state["commitments"].append({**change, "status": "confirmed" if change["operation"] == "confirm" else "cancelled",
                                    "source_message": message_id, "source": "explicit_test_message_envelope"})

    def receive(self, message_id, content, *, intent="ordinary", interrupt=False, commitment=None,
                expected_revision=None, source="explicit_test_envelope", received_at=None):
        """Receive once; explicit intent/interrupt/commitment are labelled test inputs.

        This does not infer goodnight by substring or accept invitations on behalf
        of either participant. A duplicate delivery returns its original receipt.
        """
        require(isinstance(message_id, str) and bool(message_id) and len(message_id) <= 200, "message id required")
        require(isinstance(content, str) and 0 < len(content.strip()) <= 5000, "invalid message")
        require(intent in {"ordinary", "goodnight"} and type(interrupt) is bool, "invalid test envelope")
        require(source in {"explicit_test_envelope", "local_app_message"}, "unsupported message source")
        require(expected_revision is None or type(expected_revision) is int, "invalid revision")
        request = {"content": content, "intent": intent, "interrupt": interrupt, "commitment": commitment,
                   "expected_revision": expected_revision, "source": source}
        if received_at is not None:
            request['received_at'] = utc(received_at).isoformat()
        prefix = "p3:message:" + message_id
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT request,receipt FROM life_received_messages WHERE id=?", (message_id,)).fetchone()
            if old:
                require(old[0] == canonical(request), "message id/content conflict")
                return json.loads(old[1])
            state = self.store.read(db)
            if expected_revision is not None and state["revision"] != expected_revision:
                raise Conflict("stale message snapshot")
            now = self.clock.now()
            wake = self._advance(db, state, prefix, now)
            if state["sleep"]["status"] == "recovery_required":
                # A received message establishes present interaction, not sleep in the gap.
                state["sleep"].update(status="awake", current=None, awaiting_goodnight=True)
                self._event(db, state, prefix+":recovery-contact", "recovery_contact", {
                    "message_id": message_id, "gap_sleep": "unknown", "invented_wake_reason": None}, now)
            if state["sleep"]["status"] == "sleeping":
                self._wake(db, state, prefix+":message-wake", now, "message", message_id)
                wake = "message"
            saved_activity = state["active"]
            from .daily_obligations import unresolved_before_sleep
            pending_shower = unresolved_before_sleep(
                self.p.config, state, now, getattr(self.cog, "calendar_provider", None)) \
                if intent == "goodnight" else []
            active = state["activities"].get(saved_activity) if saved_activity else None
            keep_bedtime_routine = bool(intent == "goodnight" and pending_shower and active
                                        and active.get("kind") == "showering")
            if saved_activity and (interrupt or intent == "goodnight") and not keep_bedtime_routine:
                self.p._commit_locked(db, prefix+":interrupt", {"operation": "interrupt", "payload": {
                    "activity_id": saved_activity, "reason": source + " " + message_id},
                    "expected_revision": state["revision"]}, None)
                state = self.store.read(db)
            self._commitment(state, commitment, message_id, content)
            sleep_request = "not_requested"
            if intent == "goodnight":
                if pending_shower:
                    state["sleep"].update(awaiting_goodnight=False, pending_goodnight={
                        "message_id": message_id, "accepted_at": now.isoformat(),
                        "waiting_for": [item["id"] for item in pending_shower],
                    })
                    sleep_request = "accepted_pending_bedtime_routine"
                else:
                    sleep_request = self._start_sleep(db, state, prefix, now, message_id)
            fact = {"message_id": message_id, "content": content, "intent": intent,
                    "envelope_source": source, "wake_reason": wake,
                    "sleep_request": sleep_request, "sleep_total_seconds": state["sleep"]["total_seconds"],
                    "interrupted_activity": saved_activity if (interrupt or intent == "goodnight") else None,
                    "commitment_change": commitment}
            event = self._event(db, state, prefix, "received_test_message", fact, now)
            receipt = {**event, **fact, "sleep": deepcopy(state["sleep"]), "active": state["active"]}
            db.execute("INSERT INTO life_received_messages VALUES(?,?,?)", (message_id, canonical(request), canonical(receipt)))
            if self.p.config.get("mode") == "local_single_user" and source == "local_app_message":
                if intent == "ordinary":
                    from .coarse_plan_updates import enqueue
                    enqueue(db, message_id)
                from .media_recommendations import enqueue as enqueue_media
                enqueue_media(db, message_id)
        return receipt

    def repair_stale_goodnight(self):
        """Retry the latest accepted goodnight after the retired cooking blocker."""
        with self.store.connect() as db:
            row = db.execute(
                "SELECT id,request,receipt FROM life_received_messages ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            state = self.store.read(db)
        if not row or state.get('sleep', {}).get('status') != 'awake':
            return None
        request, receipt = json.loads(row[1]), json.loads(row[2])
        if (request.get('intent') != 'goodnight'
                or receipt.get('sleep_request') != 'blocked_safe_shutdown_unconfigured'):
            return None
        repair_id = row[0] + ':stale-cooking-repair'
        return self.receive(repair_id, request['content'], intent='goodnight',
                            expected_revision=state['revision'], source='local_app_message')

    def repair_restart_cancelled_sleep(self):
        """Restore sleep cancelled by the retired restart-continuity policy."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self.store.read(db)
            if state.get('sleep', {}).get('status') != 'recovery_required':
                return None
            episodes = state['sleep'].get('episodes', [])
            episode = episodes[-1] if episodes else None
            now = self.clock.now()
            if (not episode or episode.get('wake_reason') != 'continuity_unknown'
                    or not episode.get('natural_wake_at')
                    or now >= utc(episode['natural_wake_at'])):
                return None
            episode.update(ended_at=None, wake_reason=None, settled_until=now.isoformat())
            episode.pop('continuity_lost_at', None)
            state['sleep'].update(status='sleeping', current=episode['id'], awaiting_goodnight=False)
            return self._event(db, state, 'p3:restart-sleep-repair:' + episode['id'],
                               'sleep_schedule_correction', {
                                   'episode_id': episode['id'],
                                   'effect': 'restore explicit goodnight sleep; runtime gap not credited',
                               }, now)

    def apply_explicit_wake_correction(self):
        """Apply a confirmed wake time that predates the default sleep branch."""
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self.store.read(db)
            if state.get('sleep', {}).get('status') != 'sleeping':
                return None
            episode = self._episode(state)
            wake_day = datetime.fromisoformat(episode['wake_date']).date()
            explicit = self._explicit_wake_time(wake_day, utc(episode['started_at']))
            if explicit is None:
                return None
            due, source_message = explicit
            if utc(due) >= utc(episode['natural_wake_at']):
                return None
            episode.update(natural_wake_at=utc(due).isoformat(), branch='explicit_user_wake',
                           source='explicit user wake time', wake_source_message=source_message)
            correction = self._event(db, state, 'p3:explicit-wake-correction:' + episode['id'],
                                     'sleep_schedule_correction', {
                                         'episode_id': episode['id'],
                                         'natural_wake_at': utc(due).isoformat(),
                                         'source_message': source_message,
                                     }, self.clock.now())
        self.tick('explicit-wake-correction:' + episode['id'])
        return correction

    def manual_wake(self, wake_id):
        """Explicit local control path; it never fabricates a user message."""
        require(isinstance(wake_id, str) and bool(wake_id) and len(wake_id) <= 200, "wake id required")
        event_id = "p3:wake:" + wake_id
        tick_id = "manual-wake:" + wake_id
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute('SELECT receipt FROM (SELECT rowid,"id" AS "id","request" AS "request","receipt" AS "receipt" FROM life_receipts WHERE category=\'sleep_tick\') AS life_sleep_ticks WHERE id=?', (tick_id,)).fetchone()
            if old:
                return json.loads(old[0])
            state = self.store.read(db)
            now = self.clock.now()
            self._advance(db, state, event_id, now)
            if state["sleep"]["status"] != "sleeping":
                receipt={"event_id": event_id, "revision": state["revision"], "sleep": deepcopy(state["sleep"]),
                         "wake_reason": None, "already_awake": True}
            else:
                self._wake(db, state, event_id, now, "manual", None)
                receipt={"event_id": event_id, "revision": state["revision"], "sleep": deepcopy(state["sleep"]),
                         "wake_reason": "manual", "already_awake": False}
            db.execute("INSERT INTO life_receipts(category,id,request,receipt) VALUES('sleep_tick',?,?,?)", (tick_id, canonical({"source":"local_app_control"}), canonical(receipt)))
            return receipt

    def tick(self, tick_id):
        require(isinstance(tick_id, str) and bool(tick_id), "tick id required")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute('SELECT receipt FROM (SELECT rowid,"id" AS "id","request" AS "request","receipt" AS "receipt" FROM life_receipts WHERE category=\'sleep_tick\') AS life_sleep_ticks WHERE id=?', (tick_id,)).fetchone()
            if old:
                return json.loads(old[0])
            state = self.store.read(db)
            now = self.clock.now()
            wake = self._advance(db, state, "p3:tick:"+tick_id, now)
            receipt = {"tick_id": tick_id, "at": now.isoformat(), "revision": state["revision"],
                       "wake_reason": wake, "sleep": deepcopy(state["sleep"])}
            db.execute("INSERT INTO life_receipts(category,id,request,receipt) VALUES('sleep_tick',?,?,?)", (tick_id, canonical({"at": now.isoformat()}), canonical(receipt)))
        return receipt

    def archive_chat(self, message_id):
        """Local source reference only. No LMC calls or second need update."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT request,receipt FROM life_received_messages WHERE id=?", (message_id,)).fetchone()
            require(row is not None, "unknown test message")
            request=json.loads(row[0])
            body = {"message_id": message_id, "source_event": "p3:message:"+message_id,
                    "content": json.loads(row[0])["content"], "occurred_at": json.loads(row[1])["occurred_at"],
                    "kind": ("local_app_chat_source_reference_not_LMC" if request.get("source") == "local_app_message"
                             else "isolated_chat_source_reference_not_LMC")}
            db.execute("INSERT OR IGNORE INTO life_evidence(category,id,source_id,body) VALUES('message',?,?,?)", (message_id, body["source_event"], canonical(body)))
        return body

    def reply(self, message_id, attempt_id):
        with self.store.connect() as db:
            old = db.execute("SELECT body FROM life_interaction_replies WHERE message_id=?", (message_id,)).fetchone()
            if old:
                return json.loads(old[0])
            row = db.execute("SELECT request,receipt FROM life_received_messages WHERE id=?", (message_id,)).fetchone()
        require(row is not None, "unknown test message")
        self.cog.synchronize(attempt_id+":sync")
        def build():
            context = self.cog._snapshot()
            context.update(test_message=json.loads(row[0]), message_receipt=json.loads(row[1]),
                           message_id="message:"+message_id, snapshot_id="snapshot:"+str(context["state"]["revision"]))
            context["reply_moment"] = {
                "semantics": "goodnight acknowledgement at committed sleep transition; not speech generated during unconscious sleep",
                "current_sleep_status": context["state"]["sleep"]["status"],
                "transition_message": context["state"]["sleep"].get("current") == "p3:message:"+message_id+":sleep",
                "no_unobserved_pre_sleep_actions": True}
            from .state_view import unfinished
            from .work_artifacts import public_task
            context["unfinished_matters"] = unfinished(context['state'], self.p.config)
            context["work_items"] = {k: {"definition": public_task(v), "actual_progress": context["state"]["work_items"][k]} for k,v in self.p.config.get("work_items", {}).items()}
            from .skill_reading import length, simulated, position
            context["reading_progress_contract"] = [{"activity_id": a["id"], "book": a["target"],
                "processed_characters": a["progress"], "unit": "Unicode character offset, NOT line/page/chapter/paragraph number",
                "total_characters": length(self.p.config["books"][a["target"]]),
                "reading_mode": self.p.config['books'][a['target']].get('reading_mode', 'full_text'),
                "status": a["status"], "line_page_chapter_mapping":
                    position(self.p.config['books'][a['target']], a['progress'])
                    if simulated(self.p.config['books'][a['target']]) else None}
                for a in context["state"]["activities"].values() if a["kind"] == "reading"]
            from .retrieval_query import build_query
            context['retrieval_basis'],query=build_query(context['state'],self.p.config,context['now'],
                message=json.loads(row[0])['content'],commitments=self.cog.config['commitments']+context['state'].get('commitments',[]),
                planning_reference=self.cog.planning_reference(context['now']))
            context["memories"] = self.cog.memory.retrieve(query, attempt_id+":retrieve")
            with self.store.connect() as db:
                require(db.execute("SELECT id FROM life_received_messages ORDER BY rowid DESC LIMIT 1").fetchone()[0] == message_id,
                        "newer message exists; reply to the latest message instead")
                context["conversation"] = [{"message_id": r[0], "content": json.loads(r[1])["content"],
                    "received_at": json.loads(r[2])["occurred_at"], "reply": json.loads(r[3])["reply"] if r[3] else None}
                    for r in db.execute("SELECT m.id,m.request,m.receipt,r.body FROM life_received_messages m LEFT JOIN life_interaction_replies r ON r.message_id=m.id ORDER BY m.rowid DESC LIMIT 12")][::-1]
            return context
        context, done = self.cog._prepare(attempt_id, "p3_reply:"+message_id, build)
        if done:
            return done
        try:
            output = self.cog.calls.ask(attempt_id+":reply", "p3_reply", context)
            shape(output, {"reply", "basis", "evidence_ids"})
            text(output["reply"]); text(output["basis"])
            # P1 only records character offsets. No available fixture has pagination.
            prose = output["reply"]+" "+output["basis"]
            if context["test_message"]["intent"] == "goodnight" and context["state"]["sleep"]["status"] == "sleeping":
                # Regression fence for observed defects; semantic guard still checks all other phrasing.
                require(not re.search(r"(?:准备|打算|一会儿|待会儿|还没)(?:好)?(?:去)?(?:睡|入睡|休息)|合上(?:了)?阅读的进度", output["reply"]),
                        "goodnight reply contradicts committed sleep transition")
            if context["reading_progress_contract"]:
                require(not re.search(r"(?:第)?(?:\d+|[一二三四五六七八九十百两]+)\s*(?:行|页|章|段)|(?:line|page|chapter|paragraph)\s*\d+", prose, re.I),
                        "unsupported reading line/page/chapter unit; only character offsets are known")
                reported = re.findall(r"(?:读到|读了|已读|阅读了|阅读进度为)\s*第?(\d+)\s*(?:个)?字", prose)
                require(all(int(n) in {a["processed_characters"] for a in context["reading_progress_contract"]} for n in reported),
                        "reply reading count differs from committed character progress")
            memory_ids = {m["id"] for m in context["memories"]}
            refs(output["evidence_ids"], memory_ids | {context["message_id"], context["snapshot_id"]})
            require({context["message_id"], context["snapshot_id"]} <= set(output["evidence_ids"]), "reply must cite message and snapshot")
            require(not memory_ids or memory_ids & set(output["evidence_ids"]), "reply must cite retrieved memory")
            guard = self.cog.calls.ask(attempt_id+":guard", "p3_guard", {"context": context, "proposed": output})
            shape(guard, {"approved", "issues"})
            require(guard["approved"] is True and guard["issues"] == [], "chat boundary guard rejected reply")
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute("SELECT body FROM life_interaction_replies WHERE message_id=?", (message_id,)).fetchone()
                if old:
                    receipt = json.loads(old[0])
                    self.cog._finish(db, attempt_id, receipt)
                    return receipt
                state, meta = self.cog._fresh(db, context)
                # Dialogue history is a cognition input even though reply changes no needs.
                meta["revision"] += 1
                self.cog._save_meta(db, meta)
                receipt = {**output, "message_id": message_id, "state_revision": state["revision"],
                           "model_kind": self.cog.calls.model.kind, "attempt_id": attempt_id,
                           "delivery": "isolated_output_only", "created_at": self.clock.now().isoformat()}
                db.execute("INSERT INTO life_interaction_replies VALUES(?,?,?)", (message_id, attempt_id, canonical(receipt)))
                self.cog._finish(db, attempt_id, receipt)
            return receipt
        except Exception as exc:
            self.cog._reject(attempt_id, exc)
            raise

    def inspect(self):
        from .storage_layout import audit_cursor
        # P1/P2 and P3 tables all exported under one read transaction.
        with self.store.connect() as db:
            db.execute("BEGIN")
            result = {"state": self.store.read(db), "config": self.config}
            for table in ("events", "reading_records", "results", "result_reviews", "life_observations", "life_memories",
                          "life_observation_updates", "life_model_calls", "life_cognition_runs", "life_memory_retrievals", "life_cognition_artifacts", "life_received_messages",
                          "life_sleep_ticks", "life_interaction_replies", "life_message_archive"):
                cursor = audit_cursor(db, table)
                result[table] = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
            return result
