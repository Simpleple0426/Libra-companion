"""Sentence-aware reading adapter; context never earns additional progress."""
import re
from .activity_engine import require
from .cognition_contracts import shape, text, refs


def reading_window(book_id, book, start, soft_size):
    prose = book["text"]
    require(0 <= start < len(prose), "no unread text")
    # Include closing quotation marks in the same sentence. No forward context
    # beyond the actual new interval is exposed or silently credited.
    ends = [m.end() for m in re.finditer(r'[。！？.!?\n]+[”’"」』]*', prose)]
    if not ends or ends[-1] != len(prose):
        ends.append(len(prose))
    target = min(len(prose), start + soft_size)
    end = next(n for n in ends if n >= target)
    require(end-start <= 4096, "sentence exceeds reading adapter limit; explicit handling required")
    prior_ends = [0] + [n for n in ends if n <= start]
    context_start = prior_ends[-1]
    if context_start == start and len(prior_ends) > 1:
        context_start = prior_ends[-2]
    content = {"id": f"content:{book_id}:{start}:{end}", "start": start, "end": end,
               "text": prose[start:end], "content_version": book["version"]}
    context = {"id": f"read-context:{book_id}:{context_start}:{start}", "start": context_start,
               "end": start, "text": prose[context_start:start], "role": "already_read_no_credit"}
    window = {"id": f"read-window:{book_id}:{context_start}:{end}", "start": context_start,
              "end": end, "text": prose[context_start:end], "role": "interpretation_only",
              "credited_range": {"start": start, "end": end}, "sentence_complete": True}
    return content, context, window


def validate_read(output, context):
    shape(output, {"note", "evidence_ids", "claims"})
    text(output["note"])
    sources = {context[k]["id"]: context[k] for k in ("content", "reading_context", "reading_window")}
    window, content = context["reading_window"], context["content"]
    for source in sources.values():
        require(type(source["start"]) is int and type(source["end"]) is int
                and window["start"] <= source["start"] <= source["end"] <= window["end"], "invalid source interval")
        require(source["end"]-source["start"] == len(source["text"]), "source length mismatch")
        require(source["text"] == window["text"][source["start"]-window["start"]:source["end"]-window["start"]], "source/window mismatch")
    require(context["reading_context"]["end"] == content["start"]
            and window["end"] == content["end"]
            and window["credited_range"] == {"start": content["start"], "end": content["end"]}, "invalid credit partition")
    refs(output["evidence_ids"], sources)
    require(context["content"]["id"] in output["evidence_ids"], "note must cite new reading content")
    require(isinstance(output["claims"], list) and 1 <= len(output["claims"]) <= 6, "reading claims required")
    overlaps_new = False
    aligned = []
    for claim in output["claims"]:
        shape(claim, {"statement", "quote", "evidence_id"})
        text(claim["statement"]); text(claim["quote"])
        require(claim["evidence_id"] in sources and claim["evidence_id"] in output["evidence_ids"], "unknown claim evidence")
        source = sources[claim["evidence_id"]]
        require(claim["quote"] in source["text"], "reading quote is not verbatim evidence")
        # Structural anchor only; semantic entailment is independently checked.
        matches = []
        for match in re.finditer(re.escape(claim["quote"]), source["text"]):
            start, end = source["start"]+match.start(), source["start"]+match.end()
            overlap = max(0, min(end, content["end"])-max(start, content["start"]))
            overlaps_new |= overlap > 0
            matches.append({"start": start, "end": end, "new_characters_in_quote": overlap})
        aligned.append({**claim, "source_text": source["text"],
                        "source_range": {"start": source["start"], "end": source["end"]},
                        "quote_matches": matches, "interpretation_source": window})
    require(overlaps_new, "claims only cover previously read context")
    # The published note is independently paired with the full source. Correct
    # subclaims must never let an unsupported aggregate summary pass unnoticed.
    aligned.append({"role": "published_summary_independent_assertion", "statement": output["note"],
                    "quote": window["text"], "evidence_id": window["id"], "source_text": window["text"],
                    "source_range": {"start": window["start"], "end": window["end"]},
                    "quote_matches": [{"start": window["start"], "end": window["end"],
                                       "new_characters_in_quote": content["end"]-content["start"]}],
                    "interpretation_source": window})
    return {"aligned_claims": aligned, "reading_window": window,
            "code_checks": {"verbatim_quotes": True, "source_intervals": True,
                            "credit_range": window["credited_range"],
                            "new_characters": content["end"]-content["start"],
                            "context_credit": 0}}
