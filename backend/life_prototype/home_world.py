"""Opt-in discrete household simulator, a project adapter, not D2A physics.

No model predictions or operator-supplied success results enter this evaluator.
"""
from collections import deque
from copy import deepcopy
import json
from .clock import utc
from .config import canonical, digest
from .activity_engine import require


class WorldFailure(ValueError):
    """Observed resource failure, distinct from caller/clock/protocol errors."""


def world_require(condition, message):
    if not condition: raise WorldFailure(message)


def path(config, start, end):
    require(config.get("household_world", {}).get("source") in {"test_fixture", "user_confirmed_local_single_user"}, "household world disabled")
    graph = config["household_world"]["edges"]
    queue = deque([[start]]); seen = {start}
    while queue:
        route = queue.popleft()
        if route[-1] == end: return route
        for x, y in graph:
            neighbor = y if x == route[-1] else x if y == route[-1] else None
            if neighbor and neighbor not in seen:
                seen.add(neighbor); queue.append(route+[neighbor])
    raise ValueError("no configured household path")


def available_tools(p, state):
    return state.get("available_tools", p.config["initial"]["available_tools"])


def evaluate(p, state, at):
    require(p.config.get("household_world", {}).get("source") in {"test_fixture", "user_confirmed_local_single_user"}, "household world disabled")
    a = state["activities"][state["active"]]
    require(a.get('viewing_mode') != 'active_time_simulation', 'movie skill uses active-time heartbeat, not world checkpoints')
    require(not a.get('outing_mode'), 'outing uses lifecycle events')
    require(not a.get('rest_mode'), 'rest records start/end events only')
    require(not a.get('television_mode'), 'television records switch events only')
    require(not a.get('exercise_mode'), 'exercise uses active-time settlement')
    require(not a.get('housework_mode'), 'housework uses active-time heartbeat')
    require(not a.get('work_mode'), 'daily work uses active-time heartbeat')
    require(not a.get('care_mode'), 'care skill uses active-time heartbeat')
    require(not a.get('meal_mode'), 'meal skill uses active-time heartbeat')
    require(a["status"] == "running" and utc(at) >= utc(a["next_due_at"]), "checkpoint not due")
    require((utc(at)-utc(a["last_progress_at"])).total_seconds() <= p.config["max_gap_seconds"], "unobserved gap")
    require(a["place"] == state["place"], "actor moved away from activity")
    kind = a["kind"]
    if kind == 'watching':
        movie = p.config['movies'][a['target']]
        world_require(movie.get('available', True) and state['place']==movie['place'], 'movie unavailable or wrong place')
        return {'source':'simulated_world','seconds':p.config['checkpoint_seconds'],
                'observation':'在当前观影片段中累计了一个活跃检查点的模拟观看时长；不表示整部看完，也不生成剧情或台词。'}
    if kind == "cooking":
        recipe = p.config["recipes"][a["target"]]
        world_require(recipe["tool"] in available_tools(p, state), "world failure: tool unavailable")
        world_require(p.config["objects"][recipe["tool"]]["parent"] == state["place"], "world failure: tool location")
        if not a["ingredients_consumed"]:
            try: p._resources(state, recipe)
            except ValueError as exc: raise WorldFailure(str(exc)) from exc
        step = a["progress"]+1
        require(step <= len(recipe["steps"]), "recipe already complete")
        return {"source": "simulated_world", "step": step,
                "observation": "离散测试世界已执行配方步骤："+recipe["steps"][step-1]+"；工具可用，前置进度及食材检查通过；尚未进食。"}
    if kind == "eating":
        meal = state["meals"][a["target"]]
        world_require(meal["place"] == state["place"] and meal["remaining"] > 0, "world failure: food unavailable")
        portion = min(meal["remaining"], p.config["household_world"]["portion_per_checkpoint"])
        return {"source": "simulated_world", "portion": portion,
                "observation": f"离散测试世界实际进食了现有食物的 {portion} 份；不是制作完成或预测收益。"}
    if kind == "showering":
        world_require(state["place"] == p.config["daily_routines"]["shower"]["place"],
                      "world failure: shower place unavailable")
        return {"source": "simulated_world", "observation": "在已配置的二层卫生间完成了实际洗澡时长；不是计划或预测。"}
    require(kind in {"moving", "serving"}, "world executor unsupported activity")
    route = a["route"]; index = a["progress"]
    require(route[index] == state["place"], "route position mismatch")
    require(path(p.config, route[index], route[index+1]) == route[index:index+2], "invalid passage")
    if kind == "serving":
        meal = state["meals"][a["target"]]
        world_require(meal["place"] == state["place"] and meal["remaining"] > 0, "world failure: carried food unavailable")
    return {"source": "simulated_world", "from": route[index], "to": route[index+1],
            "observation": "沿显式测试通行边完成一段移动" + ("，同一份食物随左然搬运。" if kind == "serving" else "。")}


def checkpoint(p, attempt):
    """Durable evaluation, then normal P1 staging/version checks/settlement."""
    with p.store.connect() as db:
        db.execute('SELECT 1')
        db.execute("BEGIN IMMEDIATE")
        settled = db.execute("SELECT receipt FROM results WHERE id=?", (attempt+":result",)).fetchone()
        if settled and settled[0]: return json.loads(settled[0])
        old = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_evidence WHERE category=\'world_check\') AS home_world_checks WHERE id=?', (attempt,)).fetchone()
        if old:
            check = json.loads(old[0])
        else:
            state = p.store.read(db); at = p.clock.now().isoformat()
            require(state["active"] is not None, "no active world activity")
            check = {"snapshot": state, "at": at, "activity_id": state["active"],
                     "rules_hash": digest(p.config), "adapter": ("discrete_household_v1_test_fixture" if
                        p.config["household_world"]["source"] == "test_fixture" else "confirmed_local_routine_world_v1")}
            try: check["evidence"] = evaluate(p, state, at)
            except WorldFailure as exc: check["failure"] = str(exc)
            db.execute("INSERT INTO life_evidence(category,id,body) VALUES('world_check',?,?)", (attempt, canonical(check)))
    if "failure" in check:
        return p.command("world-failure:"+attempt, check["snapshot"]["revision"], "fail",
                         activity_id=check["activity_id"], reason=check["failure"])
    p.stage_result(attempt+":result", check["snapshot"]["revision"], check["activity_id"],
                   {**check["evidence"], "world_check_id": attempt}, check["at"])
    return p.settle(attempt+":result")


def verify(p, db, evidence):
    row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_evidence WHERE category=\'world_check\') AS home_world_checks WHERE id=?', (evidence.get("world_check_id"),)).fetchone()
    require(row is not None, "missing simulator provenance")
    check = json.loads(row[0])
    from .world_extensions import historical
    original = historical(p, check["rules_hash"])
    require("evidence" in check, "world failure mismatch")
    expected = evaluate(original, check["snapshot"], check["at"])
    require(evidence == {**expected, "world_check_id": evidence["world_check_id"]}, "forged simulator result")
    return check


