"""Shared local-time boundary helpers without schedule generation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


LOCAL = timezone(timedelta(hours=8))
DAY_START_HOUR = 4


def local_time(at: datetime | None = None) -> datetime:
    value = at or datetime.now(LOCAL)
    return value.astimezone(LOCAL).replace(tzinfo=None) if value.tzinfo else value


def day_start(at: datetime | None = None) -> datetime:
    value = local_time(at)
    return (value - timedelta(hours=DAY_START_HOUR)).replace(
        hour=DAY_START_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
