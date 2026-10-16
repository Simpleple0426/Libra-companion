"""Persistent coarse intentions, routed to the current life skills.

This module never generates observations, resources, activity results or sleep.
Only the scheduler/decision writer creates agendas; UI projections are read-only.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .clock import utc
from .config import canonical, digest
from .home_world import path
from .world_extensions import edge_seconds

RULES_PATH = Path(__file__).resolve().parents[2] / "libra" / "world" / "schedule_rules.json"
LOCAL = ZoneInfo("Asia/Shanghai")
from .coarse_plan_schema import VERSION, pack, unpack


def schedule_day(now):
    return (utc(now).astimezone(LOCAL) - timedelta(hours=4)).date()


def _at(day, value):
    hour, minute = map(int, value.split(":"))
    return datetime.combine(day, datetime.min.time(), tzinfo=LOCAL).replace(hour=hour, minute=minute)


def _route(config, origin, destination):
    if config.get('mode') == 'local_single_user':
        from .coarse_plan_schema import site_id
        if site_id(origin) == site_id(destination): return [], 0
    if origin == destination:
        return [], 0
    route = path(config, origin, destination)
    return route, sum(edge_seconds(config, a, b) for a, b in zip(route, route[1:]))


def generate(config, state, now, day_fact, rules):
    from .coarse_plan_generator import generate as plan_skills
    return unpack(pack(plan_skills(config, state, now, day_fact, rules, version=VERSION,
                        local=LOCAL, schedule_day=schedule_day, at=_at, route=_route)))


class DailyAgenda:
    def __init__(self, cognition):
        self.cog, self.p, self.store = cognition, cognition.p, cognition.store
        with self.store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS life_daily_agendas (
                day TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(day, revision))""")
            from .coarse_plan_updates import initialize
            initialize(db)

    def _read(self, db, day):
        row = db.execute("SELECT body FROM life_daily_agendas WHERE day=? ORDER BY revision DESC LIMIT 1",
                         (str(day),)).fetchone()
        return unpack(json.loads(row[0])) if row else None

    def ensure(self):
        if self.p.config.get("mode") != "local_single_user":
            return None
        from .companionship import reconcile
        reconcile(self.cog)
        now = self.p.clock.now()
        state = self.p.snapshot()
        if state.get("sleep", {}).get("status") != "awake":
            return self.read(now)
        day = schedule_day(now)
        from .daily_obligations import day_fact
        fact = day_fact(_at(day, "12:00"), self.cog.calendar_provider)
        rules = json.loads(RULES_PATH.read_text(encoding="utf8"))
        from .appointments import upcoming, for_day
        with self.store.connect() as db:
            appointments = upcoming(db, now)
        day_appointments = for_day({'appointments': appointments}, day)['appointments']
        world_basis = {k:v for k,v in self.p.config.items() if k not in {'objects','books','movies','work_items'}}
        from .morning import wake_for_day
        basis = digest({"morning_wake": wake_for_day(state, day),"generator_version": VERSION, "calendar": fact, "world": world_basis, "rules": rules,
                        "commitments": [c for c in state.get("commitments", []) if c["status"] == "confirmed"],
                        "appointments": day_appointments,
                        "companion_epoch": state.get('companion_epoch', 0)})
        with self.store.connect() as db:
            old = self._read(db, day)
        if old and old["basis"] == basis:
            return old
        body = generate(self.p.config, state, now, fact, rules)
        constraints = deepcopy((old or {}).get('user_constraints', {'cancelled': [], 'appointments': []}))
        constraints['appointments'] = day_appointments
        if constraints['appointments'] or constraints['cancelled'] or constraints.get('itinerary'):
            from .coarse_plan_updates import reflow
            try:
                body = reflow(body, constraints, state, self.p.config, now)
            except ValueError as error:
                # Never silently discard an accepted user arrangement on a
                # calendar/world rebase. Keep it visible with the conflict.
                body = deepcopy(old or body)
                body["items"] = [x for x in body["items"] if utc(x["end_at"]) > now]
                for item in body["items"]:
                    item["start_at"] = max(now, utc(item["start_at"])).isoformat()
                body["calendar"] = fact
                body['user_constraints'] = constraints
                body["conflicts"] = body.get("conflicts", []) + [{"reason": "user_arrangement_rebase_requires_review", "detail": str(error)}]
        body.update(basis=basis, revision=(old["revision"] + 1 if old else 1),
                    change_reason="generator_calendar_world_or_commitments_changed" if old else "first_awake_cycle")
        if old:
            # Preserve historical intentions verbatim; revisions never rewrite facts.
            body["past_items"] = old.get("past_items", []) + [x for x in old["items"] if utc(x["end_at"]) <= now]
        for index, item in enumerate(body["items"]):
            item["id"] = f"agenda:{day}:r{body['revision']}:{index}"
        body["evidence_id"] = f"agenda:{day}:r{body['revision']}"
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._read(db, day)
            if current != old or self.store.read(db)["revision"] != state["revision"]:
                from .store import Conflict
                raise Conflict("daily agenda inputs changed; retry against current state")
            if upcoming(db, now) != appointments:
                from .store import Conflict
                raise Conflict('appointments changed during agenda generation')
            db.execute("INSERT INTO life_daily_agendas VALUES(?,?,?)", (str(day), body["revision"], canonical(pack(body))))
        return unpack(pack(body))

    def read(self, now=None):
        with self.store.connect() as db:
            return self._read(db, schedule_day(now or self.p.clock.now()))

    def view(self, now=None, *, state=None):
        now = utc(now or self.p.clock.now())
        body = self.read(now)
        if body is None:
            return None
        result = deepcopy(body)
        state = self.p.snapshot() if state is None else state
        result["current_item"] = next((x for x in result["items"] if utc(x["start_at"]) <= now < utc(x["end_at"])), None)
        result["next_item"] = next((x for x in result["items"] if utc(x["start_at"]) > now), None)
        current = result["current_item"]
        result["pending_transition"] = None
        if current:
            if current["kind"] == "commute":
                result["pending_transition"] = current
            elif current.get('activity') != 'user_time' and current["place"] != state["place"]:
                result["pending_transition"] = next((x for x in reversed(result["items"])
                    if x["kind"] == "commute" and utc(x["end_at"]) <= now
                    and x["destination"] == current["place"]), None)
        for item in result["items"]:
            if self.p.config.get('movies') and item.get('activity') in {'watch_movie','watch_show'}:
                item['execution'] = 'requires_available_target'
            actual = [a for a in state["activities"].values()
                      if item.get("reference_id") and a["target"] == item["reference_id"]]
            item["actual_activity_ids"] = [a["id"] for a in actual]
            item["status"] = ("completed" if any(a["status"] == "completed" for a in actual) else
                              "in_progress" if any(a["status"] == "running" for a in actual) else
                              "elapsed_unverified" if utc(item["end_at"]) <= now else "planned")
            if item.get('activity') == 'user_time' and (state.get('coarse_state') or {}).get('appointment_id') == item.get('appointment_id'):
                if utc(item['start_at']) <= now < utc(item['end_at']) and state.get('sleep', {}).get('status') == 'awake':
                    item['status'] = 'in_progress'
        result["actual_place"] = state["place"]
        from .coarse_plan_updates import latest
        result["message_review"] = latest(self)
        from .appointments import upcoming
        with self.store.connect() as db:
            result['upcoming_appointments'] = upcoming(db, now)
        result["upcoming_commitments"] = [c for c in result["commitments"] if utc(c["due_at"]) >= now]
        result["execution_rule"] = "Refine the current item, preserve time for the next item; if actual state or commitments conflict, replan upcoming actions. Plans grant no resources, work artifacts or sleep."
        from .companionship import current as companion_current, item as companion_item
        session = companion_current(state, now)
        result['companionships'] = deepcopy(state.get('companionships', []))
        if session:
            overlay = companion_item(session, now)
            result['current_item'] = overlay
            result['pending_transition'] = None
            result['items'] = [i for i in result['items'] if utc(i['end_at']) <= utc(session['start_at'])] + [overlay]
            if session['end_at']:
                for planned in body['items']:
                    if utc(planned['end_at']) > utc(session['end_at']):
                        planned = deepcopy(planned)
                        planned['start_at'] = max(utc(planned['start_at']), utc(session['end_at'])).isoformat()
                        result['items'].append(planned)
            result['next_item'] = next((i for i in result['items'] if utc(i['start_at']) > now), None)
        return result

    def boundary(self, now=None):
        now = utc(now or self.p.clock.now())
        from .companionship import current
        state = self.p.snapshot()
        session = current(state, now)
        if session:
            return utc(session['end_at']) if session['end_at'] else None
        body = self.read(now)
        if not body:
            return None
        points = [utc(x[k]) for x in body["items"] for k in ("start_at", "end_at") if utc(x[k]) > now]
        points += [utc(s['start_at']) for s in state.get('companionships', [])
                   if s['status'] == 'scheduled' and utc(s['start_at']) > now]
        points += [utc(c["due_at"]) for c in body["commitments"] if utc(c["due_at"]) > now]
        from .fine_plan import boundary
        fine = boundary(self.cog)
        if fine: points.append(fine)
        return min(points, default=None)
