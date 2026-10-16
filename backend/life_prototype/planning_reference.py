"""Versioned advisory anchors derived from the retired schedule rules.

The reference helps a model know the normal office and broad work windows.  It
is not a generated day, a commitment, an observed event, or execution proof.
"""
from copy import deepcopy
from datetime import timedelta
from zoneinfo import ZoneInfo

from .clock import utc
from .activity_engine import require


REFERENCE = {
    "version": "legacy-workday-reference-v2",
    "source_kind": "retired_schedule_rule_reference",
    "source_documents": [
        # These strings are versioned provenance stored in live world configs.
        # Keep their original values when moving the referenced documents.
        # Current locations: docs/life/ and docs/character/ respectively.
        "docs/左然_state_event生成规则.md sections 5.1, 5.2, 6.1, 11",
        "docs/左然律所空间与物品清单.md confirmed firm and office tree",
    ],
    "authorization": "user_authorized_for_coarse_planning_2026-09-24",
    "role": "advisory_default_not_schedule_commitment_event_or_result",
    "ordinary_workday": {"weekday_numbers": [0, 1, 2, 3, 4],
                         "calendar_exceptions": "runtime_local_work_calendar_then_weekday_fallback"},
    "office": {"place_id": "firm.office", "parent_id": "firm", "name": "左然办公室",
               "firm_name": "忒弥斯律所"},
    "arrival_window_local": {"from": "08:10", "until": "08:35"},
    "normal_end_window_local": {"from": "18:00", "until": "18:30"},
    "home_to_work_commute_minutes": {"minimum": 20, "maximum": 30,
                                     "status": "legacy_simulation_range_not_map_fact"},
    "exceptions": ["confirmed calendar override", "court or fieldwork matter",
                   "overtime decision", "leave or special schedule"],
}


def validate(reference, places):
    require(reference == REFERENCE, "unknown or modified planning reference")
    require(reference["office"]["place_id"] in places, "planning office is absent from world")
    require(reference["office"]["parent_id"] in places, "planning firm is absent from world")
    return reference


def _day_fact(day, calendar_provider):
    row = calendar_provider(day.isoformat()) if calendar_provider else None
    if row is not None:
        require(row.get("date") == day.isoformat(), "work calendar date mismatch")
        require(row.get("day_type") in {"workday", "rest_day"}, "invalid work calendar day type")
        require(row.get("rest_type") in {None, "normal_weekend", "holiday_leave"}, "invalid work calendar rest type")
        return {"date": row["date"], "day_type": row["day_type"],
                "rest_type": row.get("rest_type"), "is_adjusted": bool(row.get("is_adjusted")),
                "holiday_period": row.get("holiday_period"),
                "source": "app.work_calendar", "calendar_recorded": True}
    return {"date": day.isoformat(),
            "day_type": "workday" if day.weekday() < 5 else "rest_day",
            "rest_type": None if day.weekday() < 5 else "normal_weekend",
            "is_adjusted": False, "holiday_period": None,
            "source": "weekday_fallback_unrecorded", "calendar_recorded": False}


def view(reference, places, now, calendar_provider=None):
    validate(reference, places)
    local = utc(now).astimezone(ZoneInfo("Asia/Shanghai"))
    day = local.date()
    start_h, start_m = map(int, reference["arrival_window_local"]["from"].split(":"))
    until_h, until_m = map(int, reference["arrival_window_local"]["until"].split(":"))
    end_h, end_m = map(int, reference["normal_end_window_local"]["until"].split(":"))
    start = local.replace(year=day.year, month=day.month, day=day.day,
                          hour=start_h, minute=start_m, second=0, microsecond=0)
    until = start.replace(hour=until_h, minute=until_m)
    end = start.replace(hour=end_h, minute=end_m)
    current_day = _day_fact(day, calendar_provider)
    # Keep today's workday visible throughout its normal window.  A planner
    # running at 08:20 must not be told that the relevant workday is tomorrow.
    if current_day["day_type"] == "workday" and local <= end:
        relevant_day = day
        relevant_fact = current_day
        if local < start:
            window_status = "upcoming"
        elif local <= until:
            window_status = "current"
        else:
            window_status = "passed_for_today"
    else:
        day = local.date() + timedelta(days=1)
        relevant_fact = _day_fact(day, calendar_provider)
        checked = 1
        while relevant_fact["day_type"] != "workday" and checked < 371:
            day += timedelta(days=1)
            relevant_fact = _day_fact(day, calendar_provider)
            checked += 1
        require(relevant_fact["day_type"] == "workday", "no workday found in bounded calendar horizon")
        start = local.replace(year=day.year, month=day.month, day=day.day,
                              hour=start_h, minute=start_m, second=0, microsecond=0)
        relevant_day = day
        window_status = "upcoming"
    return {**deepcopy(reference),
            "computed": {"as_of": local.isoformat(), "relevant_ordinary_workday": relevant_day.isoformat(),
                         "arrival_window_status": window_status,
                         "seconds_until_arrival_window": int((start-local).total_seconds()),
                         "current_day": current_day, "relevant_workday": relevant_fact,
                         "calendar_exception_checked": bool(current_day["calendar_recorded"] and relevant_fact["calendar_recorded"]),
                         "meaning": "recorded work/rest calendar overrides weekday fallback; not a commitment or generated itinerary"}}


def apply_to_world(config):
    result = deepcopy(config)
    source = "docs/左然律所空间与物品清单.md user-confirmed project space"
    result["places"].update({
        "firm": {"name": "忒弥斯律所", "parent": None, "status": "confirmed", "source": source},
        "firm.office": {"name": "左然办公室", "parent": "firm", "status": "confirmed", "source": source},
    })
    result["planning_reference"] = deepcopy(REFERENCE)
    return result
