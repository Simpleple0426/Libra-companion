"""Typed movement evidence and append-only summary corrections; project adapter."""
import json
from .config import canonical, digest
from .activity_engine import require
from .cognition_contracts import shape, text


def evidence(p, db, observation):
    fact = observation["fact"]
    if fact.get("operation") != "result" or fact.get("kind") not in {"moving", "serving"}: return None
    e = fact["actual_result"]
    settled = db.execute("SELECT body,receipt FROM results WHERE id=?", (observation["source_event"].removeprefix("result:"),)).fetchone()
    require(settled is not None and settled[1] and json.loads(settled[0])["evidence"] == e,
            "movement observation requires unchanged settled result")
    from .home_world import verify
    verify(p, db, e)
    row = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","body" AS "body" FROM life_evidence WHERE category=\'world_check\') AS home_world_checks WHERE id=?', (e["world_check_id"],)).fetchone()
    require(row is not None, "movement requires saved world checkpoint")
    check = json.loads(row[0]); a = check["snapshot"]["activities"][fact["activity_id"]]
    from .world_extensions import historical
    historical(p, check["rules_hash"])
    require(e == {**check["evidence"], "world_check_id": e["world_check_id"]}, "movement evidence changed")
    index = a["progress"]; route = a["route"]
    require([e["from"], e["to"]] == route[index:index+2], "movement range mismatch")
    return {"segment_from": e["from"], "segment_to": e["to"], "final_destination": route[-1],
            "activity_completed": index+1 == len(route)-1}


def validate_facts(actual, expected):
    shape(actual, expected)
    require(type(actual["activity_completed"]) is bool, "movement completion must be boolean")
    require(actual == expected, "movement locations/completion disagree with committed checkpoint; expected="
            + canonical(expected) + "; expressed=" + canonical(actual))


def check_expression(cog, ident, payload, output):
    expected = payload["movement_evidence"]
    validate_facts(output["movement_facts"], expected)
    parsed = cog.calls.ask(ident, "movement_expression", {
        "summary": output["summary"], "place_names": payload["movement_place_names"],
        "verified_facts": expected,
        "review_contract": "natural semantic support, not literal field names; never recalculate world state",
        "required_roles": list(expected), "observation_id": payload["observation"]["id"]})
    shape(parsed, {"facts", "supported", "issues"})
    require(parsed["supported"] is True and parsed["issues"] == [], "ambiguous/unsupported movement expression")
    # Model extracts what the prose says; code compares it with the independent ledger.
    validate_facts(parsed["facts"], expected)
    return parsed


def factual_output(payload, output):
    """Public event record, never a character reply or an activity schedule."""
    facts = payload["movement_evidence"]
    record = {"source": "code_generated_verified_movement_event_not_character_dialogue", **facts}
    return {**output, "movement_facts": facts, "summary": canonical(record),
            "keywords": ["verified_movement_event", facts["segment_from"], facts["segment_to"]]}


def review_optional_expression(cog, attempt, payload, original):
    from .model_client import ModelError
    from .store import Conflict
    record = {"observation_id": payload["observation"]["id"], "original_output": original,
              "effect": "optional prose only; never world evidence or retrieval/chat input",
              "status": "reviewed_not_published"}
    try:
        text(original["summary"])
        check_expression(cog, attempt+":movement-expression", payload, original)
    except Conflict:
        raise
    except (ValueError, ModelError, KeyError, TypeError) as exc:
        record.update(status="pending_review", error={"type": type(exc).__name__, "detail": str(exc)})
    with cog.store.connect() as db:
        db.execute("INSERT INTO life_evidence(category,id,kind,body) VALUES('cognition',?,'movement_prose_review',?)",
                   (attempt+":prose-review", canonical(record)))
    return record


def corrected_summary(cog, observation_id, attempt):
    """No effect/importance replay; old update and raw memory remain immutable."""
    with cog.store.connect() as db:
        old = db.execute('SELECT body FROM (SELECT rowid,"id" AS "observation_id","body" AS "body" FROM life_evidence WHERE category=\'observation_update\') AS life_observation_updates WHERE observation_id=?', (observation_id,)).fetchone()
        require(old is not None, "correction requires settled observation")
        prior = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","kind" AS "kind","body" AS "body" FROM life_evidence WHERE category=\'cognition\') AS life_cognition_artifacts WHERE id=?', (attempt,)).fetchone()
        if prior:
            value = json.loads(prior[0]); require(value["observation_id"] == observation_id, "correction id conflict")
            return value
        original = json.loads(old[0])
        observation = json.loads(db.execute("SELECT body FROM life_observations WHERE id=?", (observation_id,)).fetchone()[0])
        facts = evidence(cog.p, db, observation)
    require(facts is not None, "movement observation required")
    context = cog._snapshot()
    payload = {"observation": observation, "movement_evidence": facts,
        "movement_place_names": {k: v["name"] for k, v in cog.p.config["places"].items()}}
    output = cog.calls.ask(attempt+":describe", "movement_summary", payload)
    shape(output, {"summary", "movement_facts"}); text(output["summary"])
    check_expression(cog, attempt+":expression", payload, output)
    record = {"observation_id": observation_id, "original_call": original["call_id"],
        "original_update_hash": digest(original), "original_summary": original["summary"],
        "corrected_summary": output["summary"], "movement_facts": facts,
        "source_world_check": observation["fact"]["actual_result"]["world_check_id"],
        "description_call": attempt+":describe", "expression_call": attempt+":expression",
        "recorded_at": cog.clock.now().isoformat(), "effect": "summary correction only; no state, need, progress or importance settlement"}
    with cog.store.connect() as db:
        db.execute("BEGIN IMMEDIATE"); cog._fresh(db, context)
        require(db.execute('SELECT body FROM (SELECT rowid,"id" AS "observation_id","body" AS "body" FROM life_evidence WHERE category=\'observation_update\') AS life_observation_updates WHERE observation_id=?', (observation_id,)).fetchone()[0] == old[0], "original update changed")
        db.execute("INSERT INTO life_evidence(category,id,kind,body) VALUES('cognition',?, 'movement_summary_correction', ?)", (attempt, canonical(record)))
    return record


def summary_view(audit):
    corrections = {}
    for row in audit["life_cognition_artifacts"]:
        if row["kind"] == "movement_summary_correction":
            record = json.loads(row["body"])
            corrections[record["observation_id"]] = (row["id"], record)
    values = []
    for row in audit["life_observation_updates"]:
        original = json.loads(row["body"]); item = {"observation_id": row["observation_id"],
            "original_summary": original["summary"], "effective_summary": original["summary"], "correction_id": None}
        if row["observation_id"] in corrections:
            ident, correction = corrections[row["observation_id"]]
            require(correction["original_update_hash"] == digest(original), "correction source mismatch")
            item.update(effective_summary=correction["corrected_summary"], correction_id=ident)
        values.append(item)
    return values
