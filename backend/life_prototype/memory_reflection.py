"""Project adaptation: provenance views and optional-reflection retry policy.

Backoff constants are isolated test defaults, not persona or production settings.
No rejected inference is a memory. Historical evidence is never stamped with the
current state version when its original version is unavailable.
"""
from copy import deepcopy
import json

RETRY_BASE_SECONDS = 300
RETRY_CAP_SECONDS = 3600


def memory_evidence(db, memory):
    sources = []
    for ident in memory.get("evidence_ids", []):
        row = db.execute("SELECT body FROM life_observations WHERE id=?", (ident,)).fetchone()
        if not row:
            continue
        obs = json.loads(row[0])
        event = db.execute("SELECT receipt FROM (SELECT rowid,id,request,receipt FROM life_receipts WHERE category='event_control') WHERE id=?", (obs["source_event"],)).fetchone()
        receipt = json.loads(event[0]) if event else {}
        sources.append({"observation_id": ident, "source_event": obs["source_event"],
            "activity_id": obs["fact"].get("activity_id"), "occurred_at": obs["occurred_at"],
            "state_revision": receipt.get("revision"), "fact": obs["fact"]})
    return {"id": memory["id"], "kind": "memory", "description": memory["description"],
        "memory_status": memory.get("status"), "created_at": memory["created_at"],
        "activity_ids": sorted({s["activity_id"] for s in sources if s["activity_id"]}),
        "sources": sources, "upstream_evidence_ids": memory.get("evidence_ids", []),
        "scope": "Only the recorded facts/inferences; null provenance is unknown, not the current version."}


def state_evidence(context, ident):
    state = deepcopy(context["state"])
    return {"id": ident, "kind": "versioned_state", "state": state,
        "state_revision": state["revision"], "as_of": state.get("as_of"),
        "observed_at": context["now"], "activity_ids": sorted(state["activities"]),
        "source": "committed_isolated_snapshot",
        "scope": "Committed values at this revision, including each keyed activity's recorded history. "
                 "Snapshot time is not every activity's event time. No inference of unrecorded events."}


def guard_context(context, output):
    """Each assertion is shown beside precisely its cited, unmodified sources."""
    catalog = {e["id"]: e for e in context["evidence_catalog"]}
    return {"now": context["now"], "persona": context.get("persona"),
        "dimensions": context.get("dimensions"), "evidence_catalog": list(catalog.values()),
        "assertion_evidence": [{"description": i["description"],
            "sources": [catalog[k] for k in i["evidence_ids"]]} for i in output["insights"]],
        "rules": "Match activity IDs before joining events. Compare event times and versions. "
                 "A later tool failure does not contradict earlier tool availability. "
                 "A cited versioned_state supports all explicitly stored fields, including progress, "
                 "ingredients_consumed, status and per-activity timestamps; not unrecorded causes or user actions."}
