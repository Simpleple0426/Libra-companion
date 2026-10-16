"""Read-only plan feasibility against executor constraints, never actual results."""
from copy import deepcopy
import math
from .clock import utc
from .activity_engine import require
from .home_world import path, available_tools
from .world_extensions import edge_seconds
from .cognition_contracts import shape


def constraints(p, state):
    from .state_view import capabilities, progress_view
    routes = []
    for start in ([] if p.config.get("mode") == "local_single_user" else p.config["places"]):
        for end in p.config["places"]:
            if start == end: continue
            try: route = path(p.config, start, end)
            except ValueError: continue
            routes.append({"from": start, "to": end, "route": route, "segments": len(route)-1,
                           "edge_seconds": [edge_seconds(p.config, x, y) for x,y in zip(route,route[1:])],
                           "minimum_seconds": sum(edge_seconds(p.config, x, y) for x,y in zip(route,route[1:]))})
    return {"source": "project_executor_constraints_test_fixture", "checkpoint_seconds": p.config["checkpoint_seconds"],
        "action_schema": {"operation_enum": ["start", "continue", "resume", "switch", "wait"],
            "kind_enum": [k for k in capabilities(p.config)["supported"] if k != "wait"] + [None],
            "new_activity": "start requires activity_id=null; never reuse a completed/failed ID",
            "existing_activity": "continue: running; resume: interrupted; identity must match",
            "wait": "activity_id, kind and target must all be JSON null; active must be null; no inspection, repair, recovery, or state effects"},
        "plan_execution_schema": {"fields": ["operation", "activity_id", "kind", "target", "scope"],
            "scope_enum": ["checkpoint", "complete"], "wait_scope": "checkpoint",
            "example": {"operation": "wait", "activity_id": None, "kind": None, "target": None, "scope": "checkpoint"}},
        "candidate_action_schema": {"fields": ["operation", "activity_id", "kind", "target"],
            "example": {"operation": "wait", "activity_id": None, "kind": None, "target": None}},
        "capabilities": capabilities(p.config),
        "activity_progress_facts": [progress_view(a, p.config) for a in state['activities'].values()],
        "routes": routes, "work_rule": "work_skill: follow saved work_steps, active time only, phase ending is not case completion" if p.config.get('work_skill') else "work requires office; scope checkpoint only, 300s fixture per stage, completion only from validated artifacts", "recipe_steps": {k: len(v["steps"]) for k, v in p.config["recipes"].items()},
        "portion_per_checkpoint": p.config["household_world"]["portion_per_checkpoint"],
        "existing_progress": [{"id": a["id"], "kind": a["kind"], "progress": a["progress"],
            "remaining_segments": len(a["route"])-1-a["progress"] if "route" in a else None,
            "next_due_at": a["next_due_at"], "status": a["status"]} for a in state["activities"].values()],
        "rule": "Only item 0 is checked for current execution. Later items are tentative intentions, never success projections or executable jobs. Checkpoint outcomes require a fresh decision after actual observations; no automatic promotion."}


def validate_intent(p, state, action):
    """References and schema only; never project a future world or grant resources."""
    op, ident, kind, target = (action[k] for k in ("operation", "activity_id", "kind", "target"))
    require(p.config.get('mode') != 'local_single_user' or kind not in {'moving', 'serving'},
            'independent movement removed; use coarse schedule')
    require(op in {"start", "continue", "resume", "switch", "wait"}, "unsupported tentative operation")
    if op == "wait":
        require(ident is None and kind is None and target is None, "invalid tentative wait")
        return
    from .daily_obligations import status as routine_status
    shower_targets = {x["id"]: x for x in routine_status(p.config, state, now=state["as_of"])
                      if x["kind"] == "shower"}
    targets = {"reading": p.config["books"], "cooking": {**p.config["recipes"],**state.get('meal_plans',{})}, "moving": p.config["places"],
               "work": {**p.config.get("work_items", {}),**state.get('work_steps',{})}, "eating": state["meals"], "serving": state["meals"],
               "outing": state.get("outing_sessions",{}), "rest": state.get("rest_sessions",{}), "television": state.get("television_sessions",{}), "exercising": state.get("exercise_sessions",{}), "housework": state.get("housework_steps",{}), "personal_care": state.get("care_plans",{}), "showering": {**shower_targets,**state.get("care_plans",{})}, "watching": p.config.get('movies', {})}
    require(kind in targets and target in targets[kind], "tentative intent references nonexistent target; no imagined food or work artifact")
    if op in {"continue", "resume"} or (op == "switch" and ident is not None):
        a = state["activities"].get(ident)
        require(a is not None and a["status"] in {"running", "interrupted"}
                and (a["kind"], a["target"]) == (kind, target), "tentative intent references terminal/unknown activity")
    else:
        require(ident is None, "tentative new activity must not invent an id")


def validate_plan(cog, plan, context):
    projected = deepcopy(context["state"])
    checks = []
    for index, item in enumerate(plan["items"]):
        require(isinstance(item.get("additional_actions", []), list), "additional_actions must be a list")
        require(not item.get("additional_actions"),
                "unsupported_capability: additional actions require explicit replanning; executor cannot absorb preparation, inspection, repair or stops: " + repr(item.get("additional_actions")))
        execution = item["execution"]
        shape(execution, {"operation", "activity_id", "kind", "target", "scope"})
        scope = execution["scope"]
        require(scope in {"checkpoint", "complete"}, "unknown plan execution scope")
        action = {k: v for k, v in execution.items() if k != "scope"}
        if action["operation"] == "wait":
            require(scope == "checkpoint", "wait plan scope must be checkpoint, not null or complete")
            require(type(item["duration_seconds"]) is int and item["duration_seconds"] > 0, "wait duration must be positive integer")
        if index > 0:
            validate_intent(cog.p, context["state"], action)
            checks.append({"plan_item": item["id"], "execution": execution,
                "minimum_seconds": None, "allocated_seconds": item["duration_seconds"], "route_check": None,
                "role": "tentative_intent", "requires_fresh_decision": True,
                "source": "reference_check_only_not_execution_feasibility_or_result"})
            continue
        require(item["start_after_seconds"] == 0, "current execution must start now; express delay as wait")
        at = utc(context["now"])
        operations = cog._validate_action(action, projected, at)
        for operation, payload in operations:
            payload = deepcopy(payload)
            if operation == "start": payload["activity_id"] = "plan-projection:"+str(index)
            cog.p._transition(projected, operation, payload, at)
        minimum = 0
        route_check = None
        if action["operation"] != "wait":
            a = projected["activities"][projected["active"]]
            kind = a["kind"]; tick = cog.p.config["checkpoint_seconds"]
            first = math.ceil(max(0, (utc(a["next_due_at"])-at).total_seconds()))
            if kind in {"moving", "serving"}:
                remaining = len(a["route"])-1-a["progress"]
                route_check = {"route": list(a["route"]), "start_index": a["progress"],
                    "end_index": len(a["route"])-1 if scope == "complete" else a["progress"]+1,
                    "first_checkpoint_wait_seconds": first, "checkpoint_seconds": tick,
                    "edge_seconds": [edge_seconds(cog.p.config,x,y) for x,y in zip(a["route"],a["route"][1:])]}
            elif a.get('work_mode'):
                remaining=1
                first=max(1,a['duration_seconds']-a['progress']) if scope=='complete' else min(tick,max(1,a['duration_seconds']-a['progress']))
            elif kind in {"work", "watching"}:
                require(scope == "checkpoint", "work artifact success uncertain; checkpoint scope required")
                remaining = 1
            elif a.get('outing_mode'):
                remaining = 1
                first = max(1, (utc(projected['outing_sessions'][a['target']]['end_at'])-at).total_seconds()) if scope=='complete' else tick
            elif a.get('rest_mode'):
                remaining = 1
                first = max(1, (utc(projected['rest_sessions'][a['target']]['end_at'])-at).total_seconds()) if scope=='complete' else tick
            elif a.get('television_mode'):
                remaining = 1
                first = max(1, (utc(projected['television_sessions'][a['target']]['end_at'])-at).total_seconds()) if scope=='complete' else tick
            elif a.get('exercise_mode') or a.get('meal_mode') or a.get('care_mode') or a.get('housework_mode'):
                remaining = 1
                first = max(1,a['duration_seconds']-a['progress']) if scope=='complete' else min(tick,max(1,a['duration_seconds']-a['progress']))
            elif kind == "cooking":
                recipe = cog.p.config["recipes"][a["target"]]
                require(recipe["tool"] in available_tools(cog.p, projected), "plan requires unavailable tool")
                remaining = len(recipe["steps"])-a["progress"]
            elif kind == "eating":
                remaining = math.ceil(projected["meals"][a["target"]]["remaining"]/cog.p.config["household_world"]["portion_per_checkpoint"])
            elif kind == "showering":
                remaining = 1
            else:
                require(scope == "checkpoint", "reading completion time unknown; plan next checkpoint only")
                remaining = 1
            minimum = first+(remaining-1)*tick if scope == "complete" else first
            if route_check and scope == "complete":
                minimum = first+sum(route_check["edge_seconds"][a["progress"]+1:])
            if route_check and item["duration_seconds"] is None:
                item["duration_seconds"] = minimum
            require(type(item["duration_seconds"]) is int and item["duration_seconds"] >= minimum, "plan duration shorter than executor minimum")
            if route_check:
                require(item["duration_seconds"] == minimum,
                        "pure movement duration differs from executor; extra time/actions require explicit replanning")
        checks.append({"plan_item": item["id"], "execution": execution, "minimum_seconds": minimum,
                       "allocated_seconds": item["duration_seconds"], "route_check": route_check,
                       "role": "current_execution", "requires_fresh_decision": False,
                       "source": "code_feasibility_only_not_result"})
    return checks


def executor_decomposition(p, item, check):
    """Deterministic route arithmetic, not a model choice or a world result."""
    route = check["route_check"]
    require(route is not None, "executor decomposition requires a known route")
    steps = []
    for index in range(route["start_index"], route["end_index"]):
        start, end = route["route"][index:index+2]
        seconds = route["first_checkpoint_wait_seconds"] if index == route["start_index"] else route["edge_seconds"][index]
        require(int(seconds) == seconds and seconds >= 0, "nonintegral executor timing")
        steps.append({"intent": "沿已配置路径从 " + p.config["places"][start]["name"] + " 前往 " + p.config["places"][end]["name"],
            "duration_seconds": int(seconds), "evidence_ids": item["evidence_ids"],
            "route_span": {"from_index": index, "to_index": index+1}})
    require(bool(steps), "no remaining movement")
    return {"plan_item_id": item["id"], "steps": steps}


def validate_decomposition(decomp, check):
    route = check["route_check"]
    if not route: return
    index = route["start_index"]
    for n, step in enumerate(decomp["steps"]):
        span = step["route_span"]
        shape(span, {"from_index", "to_index"})
        require(all(type(v) is int for v in span.values()), "integer route span required")
        require(span["from_index"] == index < span["to_index"] <= route["end_index"], "noncontiguous/out-of-range plan route")
        edges = span["to_index"]-index
        durations = route.get("edge_seconds", [route["checkpoint_seconds"]]*(len(route["route"])-1))
        minimum = sum(durations[index:span["to_index"]])
        if n == 0: minimum += route["first_checkpoint_wait_seconds"]-durations[index]
        require(step["duration_seconds"] >= minimum, "decomposition route span shorter than executor minimum")
        index = span["to_index"]
    require(index == route["end_index"], "decomposition omitted route segments")
