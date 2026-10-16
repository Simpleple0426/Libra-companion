"""Canonical serialization, hashes and shared life-world validation."""
import hashlib
import json
from datetime import datetime


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def validate(c):
    mode = c.get("mode")
    if mode not in {"isolated_test", "local_single_user"} or c.get("schema_version") != 1:
        raise ValueError("unsupported life data class/schema")
    if c["persona"]["status"] != "confirmed" or not c["persona"]["source"]:
        raise ValueError("persona requires confirmed provenance")
    nodes = c["places"] | c["objects"]
    if len(nodes) != len(c["places"]) + len(c["objects"]):
        raise ValueError("duplicate world id")
    for key, node in nodes.items():
        allowed_status = {"confirmed", "test_fixture"} if mode == "isolated_test" else {"confirmed"}
        if node["status"] not in allowed_status or not node["source"]:
            raise ValueError("unconfirmed world node")
        if mode == "local_single_user" and "test" in str(node["source"]).lower():
            raise ValueError("test world provenance cannot enter local_single_user")
        seen = {key}
        parent = node["parent"]
        while parent is not None:
            if parent not in c["places"] or parent in seen:
                raise ValueError("invalid world hierarchy")
            seen.add(parent)
            parent = c["places"][parent]["parent"]
    initial = c["initial"]
    expected_initial_source = "test_fixture" if mode == "isolated_test" else "user_confirmed"
    if initial["source"] != expected_initial_source or initial["place"] not in c["places"]:
        raise ValueError("invalid initial state provenance")
    if type(initial["hunger"]) not in (int, float) or not 0 <= initial["hunger"] <= 10:
        raise ValueError("invalid test hunger")
    for book in c["books"].values():
        if book.get('reading_mode') == 'structure_simulation':
            if (mode != 'local_single_user' or book.get('source') != 'local_library'
                    or not book.get('version') or book.get('object') not in c['objects']
                    or type(book.get('total_chars')) is not int or book['total_chars'] <= 0
                    or not book.get('structure') or book.get('text')):
                raise ValueError('invalid structure-only book')
            offset = 0
            for chunk in book['structure']:
                if chunk['start'] != offset or type(chunk['end']) is not int or chunk['end'] <= offset:
                    raise ValueError('invalid book structure offsets')
                offset = chunk['end']
            if offset != book['total_chars']:
                raise ValueError('book structure length mismatch')
            continue
        if (book["source"] != ("local_library" if mode == "local_single_user" else "test_fixture")
                or not book["version"] or not book["text"].strip()):
            raise ValueError("missing versioned fixture content")
        if book["object"] not in c["objects"]:
            raise ValueError("illegal book object")
    for recipe in c["recipes"].values():
        if (mode == "local_single_user" or recipe["source"] != "test_fixture"
                or not recipe["steps"] or not recipe["ingredients"]):
            raise ValueError("invalid fixture recipe")
        if recipe["tool"] not in c["objects"]:
            raise ValueError("illegal cooking tool")
        for item, quantity in recipe["ingredients"].items():
            if item not in c["objects"] or type(quantity) is not int or quantity <= 0:
                raise ValueError("illegal ingredient")
    for item, quantity in initial["inventory"].items():
        if item not in c["objects"] or type(quantity) is not int or quantity < 0:
            raise ValueError("invalid inventory")
    if any(tool not in c["objects"] for tool in initial["available_tools"]):
        raise ValueError("illegal available tool")
    for field in ("checkpoint_seconds", "max_gap_seconds"):
        if type(c[field]) is not int or c[field] <= 0:
            raise ValueError("invalid test timing")
    if "planning_reference" in c:
        if mode != "local_single_user":
            raise ValueError("planning reference is only valid for local_single_user")
        from .planning_reference import validate as validate_planning_reference
        validate_planning_reference(c["planning_reference"], c["places"])
    if "household_world" in c:
        w = c["household_world"]
        expected_source = "test_fixture" if mode == "isolated_test" else "user_confirmed_local_single_user"
        if w["source"] != expected_source or w["rules"] != "discrete_household_v1":
            raise ValueError("explicit household test rules required")
        if not 0 < w["portion_per_checkpoint"] <= 1 or w["dining_place"] not in c["places"]:
            raise ValueError("invalid household consumption settings")
        for x, y in w["edges"]:
            if x == y or x not in c["places"] or y not in c["places"]:
                raise ValueError("invalid household passage")
    for edge, seconds in c.get("edge_seconds", {}).items():
        if edge not in {"|".join(sorted(pair)) for pair in c.get("household_world", {}).get("edges", [])}:
            raise ValueError("timing for unconfigured edge")
        if type(seconds) is not int or not 0 < seconds <= c["max_gap_seconds"]:
            raise ValueError("invalid edge timing")
    if "daily_routines" in c:
        r = c["daily_routines"]
        if mode != "local_single_user" or r.get("version") != "user-confirmed-daily-routines-v1":
            raise ValueError("daily routines require confirmed local-single-user configuration")
        if r.get("shower", {}).get("place") not in c["places"]:
            raise ValueError("daily shower place is absent")
        if r.get("meal_resource_model") != "general_meal_available_at_valid_dining_place; food identity and inventory intentionally abstracted":
            raise ValueError("unknown meal resource model")
        if r.get("activation_at"):
            activation = datetime.fromisoformat(r["activation_at"])
            if activation.tzinfo is None or r.get("effective_from") != activation.date().isoformat():
                raise ValueError("daily routine activation boundary is invalid")
    for movie in c.get('movies', {}).values():
        if movie.get('viewing_mode') == 'active_time_simulation':
            if (movie.get('source') not in {'confirmed_movie_library', 'douban_discovery'} or movie.get('place') not in c['places']
                    or type(movie.get('duration_seconds')) is not int or movie['duration_seconds'] <= 0
                    or not movie.get('duration_source')):
                raise ValueError('movie skill requires a known movie, place and sourced duration')
    canonical(c)
