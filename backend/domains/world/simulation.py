"""Sparse life events derived from Libra's currently active schedule state."""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from domains.memory.store import tokens


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "libra" / "world" / "event_templates.json"
THREAD_CONFIG_PATH = PROJECT_ROOT / "libra" / "world" / "life_threads.json"
MOVIE_CATALOG_PATH = PROJECT_ROOT / "libra" / "movie_knowledge" / "catalog.json"


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Fail closed: absent or invalid user-approved templates mean no events."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"daily_event_limit": 0, "minimum_state_age_minutes": 25, "templates": {}}
    if not isinstance(value.get("templates"), dict):
        return {"daily_event_limit": 0, "minimum_state_age_minutes": 25, "templates": {}}
    return value


def load_thread_config(path: Path = THREAD_CONFIG_PATH) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"thread_types": {}}
    return value if isinstance(value.get("thread_types"), dict) else {"thread_types": {}}


def _known_movies(path: Path = MOVIE_CATALOG_PATH) -> list[dict]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [
        item for item in value.get("movies", [])
        if item.get("status") == "watched"
        and item.get("identity_status") in {"resolved", "assumed"}
    ]


def _location(state: dict) -> str:
    if state.get("state_type") == "commuting":
        return " → ".join(
            value for value in (
                str(state.get("from_location") or "").strip(),
                str(state.get("end_location") or "").strip(),
            ) if value
        )
    return str(state.get("from_location") or state.get("end_location") or "").strip()


def _matches(template: dict, state: dict) -> bool:
    conditions = template.get("conditions") or {}
    fragments = conditions.get("location_contains_any") or []
    location = _location(state)
    return not fragments or any(str(fragment) in location for fragment in fragments)


def _thread_matches(definition: dict, state: dict) -> bool:
    if definition.get("required_state") != state.get("state_type"):
        return False
    fragments = definition.get("location_contains_any") or []
    return not fragments or any(str(value) in _location(state) for value in fragments)


def _related_shared_history(
    connection, cues: list[str], *, limit: int = 12,
) -> dict | None:
    """Return a reviewed shared-memory scene only when a meaningful cue overlaps."""
    cue_text = " ".join(str(value).strip() for value in cues if str(value).strip())
    cue_tokens = {value for value in tokens(cue_text) if len(value) > 1}
    if not cue_tokens:
        return None
    expression = " OR ".join(
        '"' + value.replace('"', '""') + '"'
        for value in sorted(cue_tokens, key=lambda item: (-len(item), item))[:30]
    )
    rows = []
    try:
        rows = connection.execute(
            """SELECT h.payload_json,bm25(canonical_shared_history_fts) rank
               FROM canonical_shared_history_fts f
               JOIN canonical_shared_history h ON h.history_id=f.history_id
                 WHERE canonical_shared_history_fts MATCH ?
                 ORDER BY rank LIMIT ?""",
            (expression, max(1, min(limit, 20))),
        ).fetchall()
    except sqlite3.OperationalError:
        # Tests, fresh databases and degraded startup may not have the optional
        # history index yet. A life event remains valid without an association.
        rows = []
    candidates = []
    for row in rows:
        try:
            candidates.append(json.loads(row[0]))
        except (TypeError, json.JSONDecodeError):
            continue
    # Real shared life is grounded in user/libra posts and diaries created from
    # actual conversations. A moment sourced from a World Event is simulation,
    # so it must never be promoted into a real shared memory here.
    try:
        real_rows = connection.execute(
            """SELECT id,memory_type,author,content,event_date,created_at,location_text
                 FROM shared_moments
                WHERE status='published' AND source_world_event_id IS NULL
                  AND memory_type IN ('moment','diary')
                ORDER BY event_date DESC,id DESC LIMIT 120"""
        ).fetchall()
        for row in real_rows:
            candidates.append({
                "history_id": f"real_shared_moment:{row[0]}",
                "summary": str(row[3] or "")[:700],
                "evidence_quote": "",
                "tags": [str(row[1] or ""), str(row[2] or "")],
                "memory_source_type": "real_shared_memory",
                "source_ref": {
                    "table": "shared_moments", "id": int(row[0]),
                    "event_date": row[4], "created_at": row[5],
                    "location": row[6] or "",
                },
            })
    except sqlite3.OperationalError:
        pass
    ignored = {"以前", "当时", "用户", "左然", "一起", "场景", "剧情", "事情"}
    recent_usage: dict[str, datetime] = {}
    older_usage_count: dict[str, int] = {}
    usage_angles: dict[str, list[str]] = {}
    try:
        usage_rows = connection.execute(
            """SELECT occurred_at,consequence_json FROM world_events
                 WHERE consequence_json LIKE '%\"memory_recall\"%'
                 ORDER BY occurred_at DESC LIMIT 80"""
        ).fetchall()
        for usage_row in usage_rows:
            try:
                payload = json.loads(usage_row[1] or "{}")
                history_id = str((payload.get("memory_recall") or {}).get("history_id") or "")
                angle = str((payload.get("memory_recall") or {}).get("angle") or "").strip()
                used_at = datetime.fromisoformat(str(usage_row[0]).replace("Z", "+00:00"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not history_id:
                continue
            older_usage_count[history_id] = older_usage_count.get(history_id, 0) + 1
            if angle and angle not in usage_angles.setdefault(history_id, []):
                usage_angles[history_id].append(angle)
            if history_id not in recent_usage or used_at > recent_usage[history_id]:
                recent_usage[history_id] = used_at
    except sqlite3.OperationalError:
        pass
    now = datetime.now()
    best = None
    best_score = 0
    for item in candidates:
        memory_text = " ".join([
            str(item.get("summary") or ""), str(item.get("evidence_quote") or ""),
            " ".join(item.get("tags") or []),
        ])
        overlap = (cue_tokens & {value for value in tokens(memory_text) if len(value) > 1}) - ignored
        # One explicit multi-character concept such as 电影/书信/甜品 is enough;
        # generic narrative words were removed above.
        score = sum(min(len(value), 4) for value in overlap)
        if item.get("memory_source_type") == "real_shared_memory":
            # When relevance is comparable, the couple's actually lived
            # history should surface before adapted story canon.
            score += 3
        history_id = str(item.get("history_id") or "")
        last_used = recent_usage.get(history_id)
        if last_used:
            comparable_now = now.astimezone(last_used.tzinfo) if last_used.tzinfo else now
            age = comparable_now - last_used
            # A recalled scene must not be reused on the next day. After the
            # hard cooldown it returns gradually, while frequently used scenes
            # still rank below fresh alternatives.
            if age < timedelta(hours=72):
                continue
            score -= min(8, older_usage_count.get(history_id, 0) * 2)
        if score > best_score:
            best = dict(item)
            best["prior_usage_angles"] = usage_angles.get(history_id, [])
            best_score = score
    return best if best_score >= 2 else None


def _memory_recall_for_event(
    connection, chosen: dict, description: str, consequence: str, seed: str,
) -> dict | None:
    cues = [*chosen.get("memory_cues", []), description, consequence]
    memory = _related_shared_history(connection, cues)
    if not memory:
        return None
    probability = max(0.0, min(1.0, float(chosen.get("memory_recall_probability", .3))))
    if random.Random(seed + ":shared-memory").random() > probability:
        return None
    angle = "生活联想"
    text = f"{description} {consequence}"
    if any(word in text for word in ("退", "错过", "邀请", "犹豫")):
        angle = "犹豫与错过"
    elif any(word in text for word in ("选择", "判断", "责任")):
        angle = "选择与责任"
    elif any(word in text for word in ("关心", "休息", "疲惫")):
        angle = "照顾与陪伴"
    return {
        "history_id": memory["history_id"],
        "association_kind": "memory_recall",
        "claim_scope": "current_event_evoked_past_memory_only",
        "memory_source_type": memory.get("memory_source_type", "canonical_shared_past"),
        "summary": str(memory.get("summary") or "")[:500],
        "usage_summary": f"本次从“{angle}”角度联想到这段经历",
        "angle": angle,
        "source_ref": memory.get("source_ref") or {},
    }


def _insert_experience(
    connection, *, event_id: str, event_type: str, description: str,
    consequence: str, valence: float, importance: float, shareability: float,
    state: dict, now: datetime, provenance: dict, thread_id: str | None = None,
    objects: list[dict | str] | None = None,
    participants: list[dict | str] | None = None,
    memory_recall: dict | None = None,
    create_thought: bool = True,
) -> dict:
    created_at = datetime.now().isoformat()
    connection.execute(
        """INSERT OR IGNORE INTO world_events (
            event_id,event_type,description,source_state_event_id,location,state_type,
            participants_json,objects_json,valence,importance,shareability,thread_id,
            consequence_json,occurred_at,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (event_id, event_type, description, int(state["id"]), _location(state),
         state.get("state_type") or "", json.dumps(participants or [], ensure_ascii=False),
         json.dumps(objects or [], ensure_ascii=False),
         valence, importance, shareability, thread_id,
         json.dumps({
             "summary": consequence,
             **({"memory_recall": memory_recall} if memory_recall else {}),
             **provenance,
         }, ensure_ascii=False),
         now.isoformat(), created_at),
    )
    thought_id = "thought_" + hashlib.sha256(event_id.encode()).hexdigest()[:24]
    thought = f"{description.rstrip('。')}；{consequence}"
    if memory_recall:
        thought += (
            " 这件事让他联想到和用户共同经历过的一段过去："
            + str(memory_recall.get("summary") or "").strip()
            + "（只是由当前事件触发的回忆，不表示过去的物品、地点或动作仍在当前发生。）"
        )
    expires_at = now + timedelta(hours=10 if shareability >= .5 else 5)
    if create_thought:
        connection.execute(
        """INSERT OR IGNORE INTO libra_thoughts (
            thought_id,source_event_id,thread_id,content,topic_type,topic_score,
            share_value,expires_at,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (thought_id, event_id, thread_id, thought, event_type,
             min(1.0, importance * .45 + shareability * .55), shareability,
             expires_at.isoformat(), created_at),
        )
    return {
        "event_id": event_id, "event_type": event_type,
        "description": description, "occurred_at": now.isoformat(),
        "thought_id": thought_id if create_thought else None,
        "thought": thought if create_thought else None, "thread_id": thread_id,
        "importance": importance, "shareability": shareability,
        "location": _location(state), "consequence": consequence,
        "memory_recall": memory_recall,
    }


def _followup_intent(question: str) -> str | None:
    """Recognise narrow requests for a missing detail in the current life scene."""
    text = re.sub(r"[\s？?。！!，,]", "", str(question or ""))
    # Preferences, plans and hypotheticals are not missing facts about the scene.
    if any(value in text for value in (
        "喜欢吃", "爱吃", "想吃", "准备吃", "打算吃", "平时吃", "一般吃",
        "明天吃", "下次吃", "以后吃", "如果吃",
    )):
        return None
    if re.search(r"(吃|饭|午餐|晚餐|早餐).{0,4}(什么|啥|哪道|哪个菜)", text) or text in {
        "吃什么", "吃的什么", "什么饭", "什么菜",
    }:
        return "meal"
    if re.search(r"(见|遇到|碰到|和|跟).{0,3}(谁|什么人)", text) or text in {
        "见谁", "和谁", "跟谁", "遇到谁", "什么人",
    }:
        return "person"
    return None


def _expansion_matches(item: dict, state: dict) -> bool:
    conditions = item.get("conditions") or {}
    states = [str(value) for value in conditions.get("state_types", [])]
    if states and str(state.get("state_type") or "") not in states:
        return False
    fragments = [str(value) for value in conditions.get("location_contains_any", [])]
    return not fragments or any(value in _location(state) for value in fragments)


def resolve_followup_detail(
    connection, question: str, state: dict | None, now: datetime | None = None,
) -> dict | None:
    """Ground a missing everyday detail in the existing World Event template library.

    The selected detail is persisted before it is returned. Repeated questions about
    the same state therefore retrieve the same fact instead of inventing a new one.
    """
    intent = _followup_intent(question)
    if not intent or not state or state.get("id") is None:
        return None
    state = dict(state)
    state_id = int(state["id"])
    event_id = "world_detail_" + hashlib.sha256(
        f"{state_id}:{intent}".encode()
    ).hexdigest()[:24]
    existing = connection.execute(
        """SELECT event_id,event_type,description,location,state_type,
                  participants_json,objects_json,consequence_json,occurred_at
             FROM world_events WHERE event_id=?""", (event_id,),
    ).fetchone()
    if existing:
        result = dict(existing)
        result["participants"] = json.loads(result.pop("participants_json") or "[]")
        result["objects"] = json.loads(result.pop("objects_json") or "[]")
        result["metadata"] = json.loads(result.pop("consequence_json") or "{}")
        result["reused"] = True
        return result

    config = load_config()
    candidates = [
        item for item in config.get("detail_expansions", {}).get(intent, [])
        if isinstance(item, dict) and _expansion_matches(item, state)
    ]
    if not candidates:
        return None
    # Prefer a location-specific rule over a generic fallback.
    specificity = max(bool((item.get("conditions") or {}).get("location_contains_any")) for item in candidates)
    candidates = [
        item for item in candidates
        if bool((item.get("conditions") or {}).get("location_contains_any")) == specificity
    ]
    seed = f"detail:{state_id}:{intent}"
    rng = random.Random(seed)
    chosen = rng.choice(candidates)
    variants = [item for item in chosen.get("variants", []) if isinstance(item, dict)]
    if not variants:
        return None
    variant = rng.choice(variants)
    description = str(variant.get("description") or "").strip()
    answer = str(variant.get("answer") or description).strip()
    if not description or not answer:
        return None
    provenance = {
        "summary": answer,
        "detail_intent": intent,
        "trigger": "user_followup",
        "template_id": chosen.get("id"),
        "variant_id": variant.get("id"),
        "source_refs": chosen.get("source_refs", []),
        "provenance": "user_world_config",
    }
    occurred_at = now or datetime.now()
    connection.execute(
        """INSERT OR IGNORE INTO world_events (
            event_id,event_type,description,source_state_event_id,location,state_type,
            participants_json,objects_json,valence,importance,shareability,thread_id,
            consequence_json,occurred_at,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (event_id, "detail_resolution", description, state_id, _location(state),
         state.get("state_type") or "",
         json.dumps(variant.get("participants") or [], ensure_ascii=False),
         json.dumps(variant.get("objects") or [], ensure_ascii=False),
         float(variant.get("valence", .04)), float(variant.get("importance", .12)),
         float(variant.get("shareability", .12)), None,
         json.dumps(provenance, ensure_ascii=False), occurred_at.isoformat(),
         datetime.now().isoformat()),
    )
    connection.commit()
    return {
        "event_id": event_id, "event_type": "detail_resolution",
        "description": description, "location": _location(state),
        "state_type": state.get("state_type") or "",
        "participants": variant.get("participants") or [],
        "objects": variant.get("objects") or [], "metadata": provenance,
        "occurred_at": occurred_at.isoformat(), "reused": False,
    }


def _progress_due_thread(connection, state: dict, now: datetime, config: dict) -> dict | None:
    rows = connection.execute(
        """SELECT * FROM life_threads
           WHERE status='ongoing' AND next_event_after IS NOT NULL AND next_event_after<=?
           ORDER BY next_event_after,started_at LIMIT 10""", (now.isoformat(),),
    ).fetchall()
    definitions = config.get("thread_types", {})
    for raw in rows:
        thread = dict(raw)
        definition = definitions.get(thread["thread_type"])
        if not isinstance(definition, dict) or not _thread_matches(definition, state):
            continue
        thread_state = json.loads(thread.get("state_json") or "{}")
        index = int(thread_state.get("next_stage_index", 0))
        stages = definition.get("stages") or []
        if index >= len(stages):
            continue
        stage = stages[index]
        try:
            description = str(stage["description"]).format(**thread_state)
            consequence = str(stage["consequence"]).format(**thread_state)
        except (KeyError, ValueError):
            continue
        event_id = "world_" + hashlib.sha256(
            f"{thread['thread_id']}:{index}".encode()
        ).hexdigest()[:24]
        result = _insert_experience(
            connection, event_id=event_id,
            event_type=str(stage["event_type"]), description=description,
            consequence=consequence, valence=float(stage.get("valence", 0)),
            importance=float(stage.get("importance", 0)),
            shareability=float(stage.get("shareability", 0)), state=state, now=now,
            thread_id=thread["thread_id"], provenance={
                "thread_type": thread["thread_type"], "thread_stage": stage["stage"],
                "source_refs": definition.get("source_refs", []),
                "provenance": "user_world_config",
            },
        )
        next_index = index + 1
        completed = next_index >= len(stages) or stage["stage"] == "completed"
        gap = timedelta(hours=max(1, int(definition.get("minimum_gap_hours", 18))))
        connection.execute(
            """UPDATE life_threads SET stage=?,state_json=?,status=?,next_event_after=?,
               last_progressed_at=?,completed_at=?,updated_at=? WHERE thread_id=?""",
            (stage["stage"], json.dumps({**thread_state, "next_stage_index": next_index}, ensure_ascii=False),
             "completed" if completed else "ongoing",
             None if completed else (now + gap).isoformat(), now.isoformat(),
             now.isoformat() if completed else None, now.isoformat(), thread["thread_id"]),
        )
        connection.commit()
        return result
    return None


def maybe_generate(connection, state: dict | None, now: datetime | None = None) -> dict | None:
    """Create at most one idempotent event for an eligible active state."""
    if not state:
        return None
    state = dict(state)
    now = now or datetime.now()
    config = load_config()
    thread_config = load_thread_config()
    try:
        started_at = datetime.fromisoformat(str(state["start_time"]))
    except (KeyError, TypeError, ValueError):
        return None
    minimum_age = timedelta(minutes=max(1, int(config.get("minimum_state_age_minutes", 25))))
    if started_at > now or now - started_at < minimum_age:
        return None
    if state.get("end_time"):
        try:
            if datetime.fromisoformat(str(state["end_time"])) <= now:
                return None
        except ValueError:
            return None
    state_id = int(state["id"])
    if connection.execute(
        """SELECT 1 FROM world_events
           WHERE source_state_event_id=? AND event_type<>'detail_resolution'""",
        (state_id,)
    ).fetchone():
        return None

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    daily_limit = config.get("daily_event_limit")
    if isinstance(daily_limit, (int, float)) and not isinstance(daily_limit, bool):
        daily_limit = max(0, int(daily_limit))
        if connection.execute(
            """SELECT COUNT(*) FROM world_events
               WHERE occurred_at>=? AND occurred_at<?
                 AND event_type<>'detail_resolution'""",
            (day_start.isoformat(), day_end.isoformat()),
        ).fetchone()[0] >= daily_limit:
            return None

    progressed = _progress_due_thread(connection, state, now, thread_config)
    if progressed:
        return progressed

    active_types = {
        row[0] for row in connection.execute(
            "SELECT thread_type FROM life_threads WHERE status='ongoing'"
        )
    }
    definitions = thread_config.get("thread_types", {})
    templates = [
        item for item in config["templates"].get(str(state.get("state_type") or ""), [])
        if isinstance(item, dict) and _matches(item, state)
        and (
            not item.get("starts_thread")
            or (
                item["starts_thread"] not in active_types
                and item["starts_thread"] in definitions
            )
        )
    ]
    if not templates:
        return None

    seed = f"{now.date().isoformat()}:{state_id}:{state.get('state_type')}"
    rng = random.Random(seed)
    if rng.random() > .72:  # A quiet state segment is a valid result.
        return None
    recent_template_ids = {
        json.loads(row[0] or "{}").get("template_id") for row in connection.execute(
            "SELECT consequence_json FROM world_events WHERE occurred_at>=?",
            ((now - timedelta(days=2)).isoformat(),),
        )
    }
    fresh = [item for item in templates if item.get("id") not in recent_template_ids]
    pool = fresh or list(templates)
    canon_backed = [item for item in pool if item.get("canon_event_variants")]
    # Card scenes are reviewed, concrete shared history. Prefer them over a
    # generic template whenever both fit the same current state and location.
    chosen = rng.choice(canon_backed or pool)
    required = {"id", "event_type", "description", "consequence", "source_refs"}
    if not isinstance(chosen, dict) or not required.issubset(chosen):
        return None
    event_type = str(chosen["event_type"])
    description = str(chosen["description"])
    consequence = str(chosen["consequence"])
    objects: list[dict | str] = list(chosen.get("objects") or [])
    canon_variant: dict | None = None
    variants = chosen.get("detail_variants") or []
    if variants:
        valid_variants = [item for item in variants if isinstance(item, dict)]
        if valid_variants:
            variant = rng.choice(valid_variants)
            description = str(variant.get("description") or description)
            consequence = str(variant.get("consequence") or consequence)
            objects = list(variant.get("objects") or objects)
    canon_variants = [
        item for item in chosen.get("canon_event_variants", [])
        if isinstance(item, dict)
    ]
    if canon_variants and rng.random() < float(chosen.get("canon_variant_probability", .8)):
        canon_variant = rng.choice(canon_variants)
        description = str(canon_variant.get("current_description") or description)
        consequence = str(canon_variant.get("consequence") or consequence)
        objects = list(canon_variant.get("objects") or objects)
    valence = float(chosen.get("valence", 0))
    importance = float(chosen.get("importance", 0))
    shareability = float(chosen.get("shareability", 0))
    event_id = "world_" + hashlib.sha256(seed.encode()).hexdigest()[:24]
    thread_id = None
    thread_type = chosen.get("starts_thread")
    thread_state = {"next_stage_index": 0}
    if chosen.get("select_object") == "movie":
        movies = _known_movies()
        if not movies:
            return None
        selected_movie = rng.choice(movies)
        thread_state.update(
            movie_id=selected_movie["movie_id"], movie_title=selected_movie["title"]
        )
        description = f"重看《{selected_movie['title']}》时注意到一个此前忽略的叙事细节。"
        consequence = "这个细节让他对片中人物的判断有了一点变化。"
    if thread_type:
        definition = definitions[thread_type]
        thread_id = "life_" + hashlib.sha256(
            f"{thread_type}:{now.date().isoformat()}:{state_id}".encode()
        ).hexdigest()[:24]
        gap = timedelta(hours=max(1, int(definition.get("minimum_gap_hours", 18))))
        created_at = datetime.now().isoformat()
        connection.execute(
            """INSERT OR IGNORE INTO life_threads (
                thread_id,thread_type,title,stage,state_json,status,started_at,
                next_event_after,last_progressed_at,created_at,updated_at
            ) VALUES (?,?,?,?,?,'ongoing',?,?,?,?,?)""",
            (thread_id, thread_type, str(definition["title"]).format(**thread_state), "started",
             json.dumps(thread_state, ensure_ascii=False), now.isoformat(),
             (now + gap).isoformat(), now.isoformat(), created_at, created_at),
        )
    memory_recall = _memory_recall_for_event(
        connection, chosen, description, consequence, seed,
    )
    result = _insert_experience(
        connection, event_id=event_id, event_type=event_type,
        description=description, consequence=consequence, valence=valence,
        importance=importance, shareability=shareability, state=state, now=now,
        thread_id=thread_id, objects=objects, memory_recall=memory_recall, provenance={
            "template_id": chosen["id"], "source_refs": chosen["source_refs"],
            **({
                "canon_event_reference": {
                    "past_event": canon_variant.get("past_event"),
                    "angle": canon_variant.get("angle"),
                    "source_refs": canon_variant.get("source_refs", []),
                }
            } if canon_variant else {}),
            "provenance": "user_world_config",
        },
    )
    connection.commit()
    return result


def active_thread_context(connection, current_state: dict | None = None) -> str:
    rows = connection.execute(
        """SELECT thread_id,thread_type,title,stage,state_json,last_progressed_at
           FROM life_threads WHERE status='ongoing' ORDER BY updated_at DESC LIMIT 5"""
    ).fetchall()
    if not rows:
        return ""
    items = []
    current_state = dict(current_state) if current_state else None
    for row in rows:
        item = dict(row)
        state = json.loads(item.pop("state_json") or "{}")
        item["details"] = state
        item["happening_now"] = bool(
            current_state
            and item["thread_type"] == "movie_reflection"
            and current_state.get("state_type") == "leisure"
            and any(value in _location(current_state) for value in ("影音", "影院", "电影院"))
        )
        items.append(item)
    return (
        "\n<active_life_threads>\n"
        "这些是持久化的进行中生活线。只有 happening_now=true 才能说此刻正在进行；"
        "否则只能说最近在做或尚未完成。没有列出的具体书、电影或项目不得临时编造。\n"
        + json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        + "\n</active_life_threads>"
    )


def context_for(connection, query: str, current_state: dict | None = None,
                limit: int = 4) -> str:
    """Retrieve query-relevant Libra world facts plus ongoing life threads."""
    query_tokens = {value for value in tokens(str(query or '')) if len(value) > 1}
    ranked = []
    if query_tokens:
        rows = connection.execute(
            """SELECT event_id,event_type,description,location,state_type,
                      participants_json,objects_json,importance,shareability,
                      thread_id,consequence_json,occurred_at
                 FROM world_events ORDER BY occurred_at DESC LIMIT 120"""
        ).fetchall()
        for position, row in enumerate(rows):
            item = dict(row)
            searchable = ' '.join([
                str(item.get('event_type') or ''), str(item.get('description') or ''),
                str(item.get('location') or ''), str(item.get('state_type') or ''),
                str(item.get('consequence_json') or ''),
            ])
            event_tokens = {value for value in tokens(searchable) if len(value) > 1}
            overlap_count = len(query_tokens & event_tokens)
            if not overlap_count:
                continue
            score = overlap_count / max(1, math.sqrt(len(query_tokens) * len(event_tokens)))
            score += max(0.0, min(float(item.get('importance') or 0), 1.0)) * .08
            score += 1 / (1000 + position)
            ranked.append((score, item))
    events = []
    for _, item in sorted(ranked, key=lambda pair: pair[0], reverse=True)[:max(1, min(limit, 8))]:
        try:
            participants = json.loads(item.pop('participants_json') or '[]')
            objects = json.loads(item.pop('objects_json') or '[]')
            consequence = json.loads(item.pop('consequence_json') or '{}')
        except (TypeError, json.JSONDecodeError):
            participants, objects, consequence = [], [], {}
        events.append({**item, 'participants': participants, 'objects': objects,
                       'metadata': consequence, 'reality_scope': 'libra_world'})
    threads = active_thread_context(connection, current_state)
    if not events:
        return threads
    return (
        '\n<world_event_knowledge>\n'
        '以下是你的生活中已记录且与当前问题相关的事件，只能作为你自身的经历引用；'
        '除非 participants 明确同时包含 user 与 libra，否则不得说成双方共同经历。'
        '历史事件不代表此刻仍在发生，当前状态以 current context 为准。\n'
        + json.dumps(events, ensure_ascii=False, separators=(',', ':'))
        + '\n</world_event_knowledge>' + threads
    )


def available_thoughts(
    connection,
    now: datetime | None = None,
    limit: int = 3,
    source_state_event_id: int | None = None,
) -> list[dict]:
    now = now or datetime.now()
    connection.execute(
        "UPDATE libra_thoughts SET status='expired' "
        "WHERE status='available' AND expires_at IS NOT NULL AND expires_at<=?",
        (now.isoformat(),),
    )
    state_clause = " AND e.source_state_event_id=?" if source_state_event_id is not None else ""
    parameters = [now.isoformat()]
    if source_state_event_id is not None:
        parameters.append(int(source_state_event_id))
    parameters.append(max(1, min(limit, 10)))
    rows = connection.execute(
        """SELECT t.*,e.description AS event_description,e.location,e.occurred_at
           FROM libra_thoughts t JOIN world_events e ON e.event_id=t.source_event_id
           WHERE t.status='available' AND (t.expires_at IS NULL OR t.expires_at>?)
        """ + state_clause + " ORDER BY t.topic_score DESC,t.created_at DESC LIMIT ?",
        parameters,
    ).fetchall()
    connection.commit()
    return [dict(row) for row in rows]


def mark_thought_shared(connection, thought_id: str, message_id: int | None = None) -> bool:
    cursor = connection.execute(
        "UPDATE libra_thoughts SET status='shared',shared_message_id=? "
        "WHERE thought_id=? AND status='available'", (message_id, thought_id),
    )
    connection.commit()
    return cursor.rowcount > 0
