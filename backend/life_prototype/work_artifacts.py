"""Evidence-bound work artifacts: project adapter, not research world physics."""
import json
from .config import canonical, digest
from .activity_engine import require
from .cognition_contracts import shape
from .clock import utc

INSTRUCTION = '''Return JSON {stage: integer, entries: [{source_id, quote, field, quantity, status}], discrepancy: integer|null, summary: string}.
Process only the supplied fictional test materials, not past cases or user actions. Each material must have exactly one entry citing an exact contiguous quotation that occurs uniquely within that source. Do not output offsets: code locates the unchanged quote in the versioned source. If a phrase repeats, quote a longer contiguous passage with distinguishing context; never guess an occurrence. Infer quantity and evidence type from the text: field is required/received/in_transit; status is requirement/actual/forecast. Requirement is not actual; forecast is not delivery. Stage 1 extracts facts; discrepancy must be null. Stage 2 uses the saved first artifact and calculates required minus actually received. Summary describes only this stage's work; no legal judgment, client contact, invented delivery or other action. No plan/forecast can complete work.'''


def locate(text, quote):
    """Exact Python Unicode code-point offsets; no normalization or rewriting."""
    require(isinstance(quote, str) and bool(quote), "empty work quotation")
    start = text.find(quote)
    require(start >= 0, "work quotation has no match")
    require(text.find(quote, start+1) < 0,
            "ambiguous work quotation: supply distinguishing contiguous context or an explicit unique fragment")
    return start, start+len(quote)


def localization(output, context, aligned):
    return {"contract": "code_located_work_v2", "materials_version": digest(context["task"]),
        "model_output_hash": digest(output), "offset_unit": "Python Unicode code points; half-open",
        "entries": [{"source_id": e["original_source_id"], "source_text_hash": digest(e["original_text"]),
            "quote": e["claim"]["quote"], "start": e["range"][0], "end": e["range"][1]}
            for e in aligned["aligned_evidence"]]}


def public_task(task):
    """Allowlist: oracle metadata and completion answers never enter inference."""
    return {**{k: task[k] for k in ("id", "source", "title", "goal", "responsibility", "deadline", "place", "stages")},
            "materials_version": digest(task),
            "materials": [{"id": m["id"], "text": m["text"]} for m in task["materials"]]}


def model_input(context):
    return {"task": public_task(context["task"]), **{k: context[k] for k in
        ("activity_id", "target", "progress", "prior_artifacts", "now")}}


def validate(output, context):
    shape(output, {"stage", "entries", "discrepancy", "summary"})
    task = context["task"]; n = context["progress"]+1
    located = context.get("input_contract") == "public_work_v2"
    require(type(output["stage"]) is int and output["stage"] == n <= 2, "work stage mismatch")
    require(isinstance(output["summary"], str) and bool(output["summary"].strip()), "missing work summary")
    require(isinstance(output["entries"], list) and len(output["entries"]) == len(task["materials"]), "all work sources required")
    seen = set(); aligned = []
    for entry in output["entries"]:
        fields = {"source_id", "quote", "field", "quantity", "status"}
        shape(entry, fields if located else fields | {"start", "end"})
        source = next((m for m in task["materials"] if m["id"] == entry["source_id"]), None)
        require(source is not None and source["id"] not in seen, "unknown/repeated work source")
        seen.add(source["id"])
        start, end = locate(source["text"], entry["quote"]) if located else (entry["start"], entry["end"])
        require(type(start) is int and type(end) is int and 0 <= start < end <= len(source["text"]), "invalid work quote range")
        require(entry["quote"] == source["text"][start:end], "work quotation mismatch")
        require(type(entry["quantity"]) is int and all(entry[k] == source[k] for k in ("field", "quantity", "status")), "work fact/forecast mismatch")
        aligned.append({"claim": entry, "original_source_id": source["id"], "original_text": source["text"], "range": [start, end]})
    required = sum(m["quantity"] for m in task["materials"] if m["field"] == "required" and m["status"] == "requirement")
    received = sum(m["quantity"] for m in task["materials"] if m["field"] == "received" and m["status"] == "actual")
    require(output["discrepancy"] is None if n == 1 else type(output["discrepancy"]) is int and output["discrepancy"] == required-received, "work discrepancy mismatch")
    require(n == 1 or len(context["prior_artifacts"]) == 1, "stage two requires committed first artifact")
    result = {"stage": n, "aligned_evidence": aligned, "summary": output["summary"],
            "discrepancy": output["discrepancy"], "prior_artifacts": context["prior_artifacts"],
            "rule": "Assess every prose claim against quotations; forecast cannot become actual. Test memo only, no legal case outcome."}
    if located:
        result["code_checks"] = {"unique_exact_quote_matches": True, "materials_version": digest(task),
            "offsets": "code-generated Python Unicode code points; do not recount; assess semantic support and summary instead"}
    return result


def provenance(p, db, evidence):
    call_id = evidence["work_call_id"]
    row = db.execute("SELECT request,response,status FROM life_model_calls WHERE id=? AND stage='work'", (call_id,)).fetchone()
    require(row is not None and row[2] == "received", "missing work model provenance")
    sent, output = json.loads(row[0])["payload"], json.loads(row[1])
    frozen = db.execute("SELECT context FROM life_cognition_runs WHERE id=? AND kind='work'", (call_id.removesuffix(":work"),)).fetchone()
    require(frozen is not None, "missing frozen work context")
    context = json.loads(frozen[0])
    located = context.get("input_contract") == "public_work_v2"
    require(set(evidence) == {"source", "work_call_id", "artifact"} | ({"localization_id"} if located else set()), "invalid work evidence")
    # Historical requests remain readable; new requests always use the allowlist.
    expected = model_input(context) if context.get("input_contract") in {"public_work_v1", "public_work_v2"} else context
    require(sent == expected, "work public input/frozen oracle mismatch")
    require(output == evidence["artifact"], "changed work artifact")
    aligned = validate(output, context)
    if located:
        require(evidence["localization_id"] == call_id+":locations", "work localization identity mismatch")
        saved = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","kind" AS "kind","body" AS "body" FROM life_evidence WHERE category=\'cognition\') AS life_cognition_artifacts WHERE id=? AND kind=\'work_localization\'', (evidence["localization_id"],)).fetchone()
        require(saved is not None and json.loads(saved[0]) == localization(output, context, aligned),
                "work localization/source/version mismatch")
    guard = db.execute("SELECT request,response,status FROM life_model_calls WHERE id=? AND stage='guard'", (call_id+":guard",)).fetchone()
    require(guard is not None and guard[2] == "received", "missing work semantic guard")
    payload = json.loads(guard[0])["payload"]
    require(payload["context"] == aligned and payload["proposed"] == output, "work guard input mismatch")
    decision = json.loads(guard[1])
    require(decision.get("approved") is True and decision.get("issues") == [], "work semantic rejection")
    task = p.config["work_items"][context["target"]]
    require(digest(task) == digest(context["task"]), "work materials version changed")
    return context


def checkpoint(cog, attempt):
    def build():
        context = cog._snapshot(); s = context["state"]; a = s["activities"][s["active"]]
        require(a["kind"] == "work" and a["status"] == "running" and utc(a["next_due_at"]) <= cog.clock.now(), "work checkpoint not due")
        job = s["work_items"][a["target"]]
        context.update(activity_id=a["id"], target=a["target"], task=cog.p.config["work_items"][a["target"]],
                       progress=job["progress"], prior_artifacts=job["artifacts"], input_contract="public_work_v2")
        context["source_ranges"] = [{"source_id": m["id"], "start": 0, "end": len(m["text"]), "quote": m["text"]} for m in context["task"]["materials"]]
        return context
    context, done = cog._prepare(attempt, "work", build)
    if done: return done
    try:
        call = attempt+":work"
        output = cog.calls.ask(call, "work", model_input(context))
        aligned = validate(output, context)
        positions = localization(output, context, aligned)
        with cog.store.connect() as db:
            old = db.execute('SELECT body FROM (SELECT rowid,"id" AS "id","kind" AS "kind","body" AS "body" FROM life_evidence WHERE category=\'cognition\') AS life_cognition_artifacts WHERE id=?', (call+":locations",)).fetchone()
            require(old is None or json.loads(old[0]) == positions, "work localization conflict")
            db.execute("INSERT OR IGNORE INTO life_evidence(category,id,kind,body) VALUES('cognition',?,'work_localization',?)", (call+":locations", canonical(positions)))
        cog._guard(call+":guard", "work_content", aligned, output)
        cog.p.stage_result(attempt+":result", context["state"]["revision"], context["activity_id"],
                           {"source": "model_work", "work_call_id": call, "artifact": output,
                            "localization_id": call+":locations"}, context["now"])
        receipt = cog.p.settle(attempt+":result")
        with cog.store.connect() as db: cog._finish(db, attempt, receipt)
        return receipt
    except Exception as exc:
        cog._reject(attempt, exc)
        raise
