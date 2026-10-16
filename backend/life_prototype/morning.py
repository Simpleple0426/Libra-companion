"""Morning care follows a committed wake, never the living-day rollover."""
from .clock import utc
from .coarse_plan import LOCAL


def wake_for_day(state, day):
    wake = (state.get('sleep') or {}).get('last_wake') or {}
    at = wake.get('at')
    return at if at and utc(at).astimezone(LOCAL).date() == day else None


def ready(state, at):
    wake = wake_for_day(state, utc(at).astimezone(LOCAL).date())
    return bool(state.get('sleep', {}).get('status') == 'awake' and wake and utc(wake) <= utc(at))
