"""UTC clocks. Advancing the manual clock never settles an activity."""
from datetime import datetime, timedelta, timezone


def utc(value: str | datetime) -> datetime:
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone required")
    return value.astimezone(timezone.utc)


class RealClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class TestClock:
    __test__ = False

    def __init__(self, value: str):
        self.value = utc(value)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int):
        if seconds < 0:
            raise ValueError("negative clock advance")
        self.value += timedelta(seconds=seconds)
