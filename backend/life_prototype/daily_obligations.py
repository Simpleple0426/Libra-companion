"""User-confirmed daily meal and evening shower obligations.

This is a project scheduling/execution adaptation, not a D2A mechanism and not
the retired whole-day schedule generator.  General meals intentionally abstract
food identity and inventory; elapsed eating is still required before settlement.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .clock import utc
from .activity_engine import require

LOCAL = ZoneInfo("Asia/Shanghai")


def local_day(now):
    return utc(now).astimezone(LOCAL)


def _at(local, value):
    hour, minute = map(int, value.split(":"))
    return local.replace(hour=hour, minute=minute, second=0, microsecond=0)


def descendant(config, place, ancestor):
    while place is not None:
        if place == ancestor:
            return True
        place = config["places"][place]["parent"]
    return False


def day_fact(local, provider):
    row = provider(local.date().isoformat()) if provider else None
    if row:
        require(row["day_type"] in {"workday", "rest_day"}, "invalid routine calendar fact")
        return {**row, "source": "app.work_calendar", "calendar_recorded": True}
    return {"date": local.date().isoformat(),
            "day_type": "workday" if local.weekday() < 5 else "rest_day",
            "rest_type": None if local.weekday() < 5 else "normal_weekend",
            "is_adjusted": False, "holiday_period": None,
            "source": "weekday_fallback_unrecorded", "calendar_recorded": False}


def target(day, name):
    return f"routine:{day}:{name}"


def status(config, state, now, provider=None):
    rules = config.get("daily_routines")
    if not rules:
        return []
    local = local_day(now); day = local.date().isoformat()
    if day < rules["effective_from"]:
        return []
    activated_at = rules.get("activation_at")
    activation = datetime.fromisoformat(activated_at).astimezone(LOCAL) if activated_at else None
    if activation and local < activation:
        return []
    fact = day_fact(local, provider)
    windows = rules["meal_windows"]["workday" if fact["day_type"] == "workday" else "rest_day"]
    activities = state["activities"].values()
    rows = []
    for name in ("breakfast", "lunch", "dinner"):
        ident = target(day, name); start, latest = (_at(local, x) for x in windows[name])
        completed = any(a["kind"] == "eating" and a["target"] == ident and a["status"] == "completed"
                        for a in activities)
        skipped = bool(activation and day == activation.date().isoformat() and latest < activation)
        rows.append({"id": ident, "kind": "meal", "meal": name, "date": day,
                     "status": "completed" if completed else "not_applicable_before_activation" if skipped else "overdue" if local > latest else
                               "due" if local >= start else "upcoming",
                     "window_start": start.isoformat(), "latest_start": latest.isoformat(),
                     "required": not skipped, "day_fact": fact,
                     "resource_model": rules["meal_resource_model"]})
    shower_id = target(day, "shower")
    shower_done = any(a["kind"] == "showering" and a["target"] == shower_id and a["status"] == "completed"
                      for a in activities)
    at_home = descendant(config, state["place"], "home")
    available = max(_at(local, "18:00"), _at(local, rules["shower"]["available_after"]))
    rows.append({"id": shower_id, "kind": "shower", "date": day,
                 "status": "completed" if shower_done else "due_flexible" if at_home and local >= available else
                           "waiting_for_home" if local >= available else "upcoming",
                 "available_after": available.isoformat(), "required_before_sleep": True,
                 "place": rules["shower"]["place"], "duration_seconds": rules["shower"]["duration_seconds"],
                 "sequence": "flexible_after_arrival; other reasonable activities allowed before sleep"})
    return rows


def unresolved_before_sleep(config, state, now, provider=None):
    return [x for x in status(config, state, now, provider)
            if x["kind"] == "shower" and x["status"] == "due_flexible"]


def enforce_meal_action(config, state, now, action, provider=None):
    """A due mandatory meal may only be approached or actually eaten."""
    due = [x for x in status(config, state, now, provider)
           if x["kind"] == "meal" and x["status"] in {"due", "overdue"}]
    if not due:
        return
    obligation = due[0]
    meal = state["meals"].get(obligation["id"])
    require(meal is not None, "mandatory meal resource has not been materialized")
    op = action["operation"]
    if op in {"continue", "resume"}:
        activity = state["activities"].get(action["activity_id"])
        require(activity and ((activity["kind"] == "eating" and activity["target"] == obligation["id"])
                or (activity["kind"] == "moving" and activity["target"] == meal["place"])),
                "mandatory meal is due; continue movement to dining or its actual eating activity")
        return
    require(action["kind"] == "eating" and action["target"] == obligation["id"]
            or action["kind"] == "moving" and action["target"] == meal["place"],
            "mandatory meal is due; only movement to its dining place or actual eating is legal")
