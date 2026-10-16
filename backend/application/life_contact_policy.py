"""Low-frequency policy for turning life facts into proactive chat candidates."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


MIN_GAP_SECONDS = 0
REPORT_GAP_SECONDS = 0


def _site_boundary(item: dict) -> bool:
    return ((item.get('detail') or {}).get('hierarchy') == 'coarse_location_boundary'
            or str(item.get('id') or '').startswith('coarse-location:'))


def report_kind(item: dict) -> str | None:
    """Recognize committed reporting milestones, never a predicted arrival."""
    kind = item.get('kind')
    if kind == 'meal_start':
        return 'meal'
    if kind in {'work_start', 'work_arrival'}:
        return 'work'
    if kind == 'arrived' and item.get('event', '').strip() == '左然回到了家':
        return 'home_arrival'
    if (kind == 'arrived'
            and _site_boundary(item)
            and '律所' in item.get('event', '')):
        return 'work_arrival'
    return None

_ALWAYS_REVIEW = {
    "woke",
    "sleep_started",
    "work_start",
    "work_arrival",
    "work_break_start",
    "meal_start",
    "rest_start",
    "reading_start",
    "watching_start",
    "care_start",
    "exercise_start",
    "outing_start",
    "user_time_start",
    "companion_update",
    "reading_completed",
    "watching_completed",
    "agenda_clarify",
    "agenda_needs_review",
    "agenda_expired",
    "life_input_failed",
    "life_input_expired",
}


def candidate(item: dict) -> tuple[bool, str]:
    """Return whether a committed fact is meaningful enough for contact review."""
    kind = str(item.get("kind") or "")
    if kind in _ALWAYS_REVIEW:
        return True, "meaningful_life_milestone"
    if kind in {"moving_start", "arrived"}:
        if _site_boundary(item):
            return True, "site_boundary"
        return False, "room_or_same_site_movement"
    return False, "routine_detail"


def availability(
    now: datetime,
    *,
    last_sent_at: str | None,
    sent_day: str | None,
    sent_count: int,
    min_gap_seconds: int = MIN_GAP_SECONDS,
) -> tuple[bool, str]:
    """No default time cooldown or daily cap; explicit caller limits remain supported."""
    local_now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    if last_sent_at and min_gap_seconds > 0:
        try:
            previous = datetime.fromisoformat(last_sent_at)
            if previous.tzinfo is not None:
                previous = previous.astimezone(local_now.tzinfo).replace(tzinfo=None)
            if (local_now.replace(tzinfo=None) - previous).total_seconds() < min_gap_seconds:
                return False, "shared_cooldown"
        except (TypeError, ValueError):
            pass
    return True, "available"
