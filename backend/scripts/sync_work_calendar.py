import argparse
import json
import urllib.request
from datetime import date, timedelta

from infrastructure.sqlite.database import init_database, replace_work_calendar_year


DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/Dreace/ChinaHolidayAPI/"
    "master/holidays/{year}.json"
)


def _holiday_period(note: str) -> str | None:
    value = note.strip()
    if value.endswith("补班"):
        value = value[: -len("补班")]
    return f"{value}假期" if value else None


def build_year(year: int, special_days: dict[str, dict]) -> list[dict]:
    current = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    days = []
    while current < end:
        date_text = current.isoformat()
        special = special_days.get(date_text)
        weekend = current.weekday() >= 5
        if special is None:
            day_type = "rest_day" if weekend else "workday"
            rest_type = "normal_weekend" if weekend else None
            is_adjusted = False
            holiday_period = None
        elif special.get("type") == "补班日":
            day_type = "workday"
            rest_type = None
            is_adjusted = weekend
            holiday_period = _holiday_period(str(special.get("note", "")))
        else:
            day_type = "rest_day"
            rest_type = "holiday_leave"
            is_adjusted = not weekend
            holiday_period = _holiday_period(str(special.get("note", "")))
        days.append(
            {
                "date": date_text,
                "day_type": day_type,
                "rest_type": rest_type,
                "is_adjusted": is_adjusted,
                "holiday_period": holiday_period,
            }
        )
        current += timedelta(days=1)
    return days


def sync(years: list[int], source: str = DEFAULT_SOURCE) -> dict[int, int]:
    init_database()
    synced = {}
    for year in years:
        request = urllib.request.Request(
            source.format(year=year),
            headers={"User-Agent": "Libra-Companion/1.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            special_days = json.loads(response.read().decode("utf-8"))
        synced[year] = replace_work_calendar_year(
            year, build_year(year, special_days)
        )
    return synced


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync China's work/rest calendar")
    parser.add_argument("years", nargs="+", type=int)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    args = parser.parse_args()
    for synced_year, count in sync(args.years, args.source).items():
        print(f"{synced_year}: {count} days")
