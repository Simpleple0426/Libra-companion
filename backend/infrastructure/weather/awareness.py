import hashlib
import json
import math
from datetime import datetime, timedelta


TEMPERATURE_DELTA = 1.2
TEMPERATURE_COOLDOWN = timedelta(minutes=45)
CONDITION_COOLDOWN = timedelta(minutes=15)


def describe_change(event: dict) -> str:
    """Render observed changes without adding advice or inferred conditions."""
    facts = event.get('facts') or {}
    places = list(dict.fromkeys(str(facts.get(key) or '').strip()
                                for key in ('city', 'district')))
    location = ''.join(places)
    subject = '用户所在区域' + (f'（{location}）' if location else '')
    parts = []
    for change in event.get('changes', []):
        if change.get('kind') == 'condition':
            before = str(change.get('from') or '').strip()
            after = str(change.get('to') or '').strip()
            if before and after:
                parts.append(f'天气由{before}转为{after}')
            elif after:
                parts.append(f'当前天气为{after}')
        elif change.get('kind') == 'temperature':
            before, after = change.get('from'), change.get('to')
            if not all(type(value) in (int, float) and math.isfinite(value) for value in (before, after)):
                continue
            delta = round(after - before, 1)
            if delta:
                direction = '上升' if delta > 0 else '下降'
                parts.append(f'气温从{before:g}℃变为{after:g}℃，{direction}{abs(delta):g}℃')
    return subject + ('，'.join(parts) if parts else '天气观测发生变化，具体变化信息不完整') + '。'


def condition_group(condition: str) -> str:
    if "雷" in condition:
        return "thunderstorm"
    if any(word in condition for word in ("暴雨", "大雨")):
        return "heavy_rain"
    if "雨" in condition:
        return "rain"
    if any(word in condition for word in ("暴雪", "大雪")):
        return "heavy_snow"
    if "雪" in condition:
        return "snow"
    if "雾" in condition:
        return "fog"
    if any(word in condition for word in ("霾", "沙尘", "扬沙", "浮尘")):
        return "haze_or_dust"
    if "风" in condition:
        return "wind"
    if any(word in condition for word in ("晴", "少云")):
        return "clear"
    if "多云" in condition:
        return "cloudy"
    if "阴" in condition:
        return "overcast"
    return "other"


def make_reading(weather: dict, observed_at: datetime) -> dict:
    condition = str(weather.get("current_weather") or "").strip()
    is_daytime = weather.get("is_daytime") is True
    return {
        "observed_at": observed_at.isoformat(),
        "city": str(weather.get("city") or ""),
        "district": str(weather.get("district") or ""),
        "temperature": float(weather.get("temperature") or 0),
        "condition": condition,
        "condition_group": condition_group(condition),
        "daylight": "day" if is_daytime else "night",
        "is_daytime": is_daytime,
        "sunrise": str(weather.get("sunrise") or ""),
        "sunset": str(weather.get("sunset") or ""),
    }


def detect_change(current: dict, delivered: dict | None, now: datetime) -> dict | None:
    if not delivered:
        return None
    try:
        delivered_at = datetime.fromisoformat(str(delivered["observed_at"]))
    except (KeyError, TypeError, ValueError):
        return None

    elapsed = now - delivered_at
    old_group = str(delivered.get("condition_group") or "other")
    new_group = str(current.get("condition_group") or "other")
    condition_changed = old_group != new_group
    severe = new_group in {"thunderstorm", "heavy_rain", "heavy_snow"}
    temperature_delta = round(
        float(current.get("temperature") or 0)
        - float(delivered.get("temperature") or 0),
        1,
    )
    temperature_changed = (
        abs(temperature_delta) >= TEMPERATURE_DELTA
        and elapsed >= TEMPERATURE_COOLDOWN
    )
    if not ((condition_changed and (severe or elapsed >= CONDITION_COOLDOWN)) or temperature_changed):
        return None

    changes = []
    if condition_changed:
        changes.append({
            "kind": "condition",
            "from": delivered.get("condition", ""),
            "to": current.get("condition", ""),
        })
    if temperature_changed:
        changes.append({
            "kind": "temperature",
            "from": delivered.get("temperature"),
            "to": current.get("temperature"),
            "delta": temperature_delta,
        })

    identity = json.dumps(
        [current.get("observed_at"), new_group, current.get("temperature")],
        ensure_ascii=False,
    )
    return {
        "event_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20],
        "source": "weather_observer",
        "event_type": "weather.changed",
        "occurred_at": current["observed_at"],
        "priority": "high" if severe else "normal",
        "facts": current,
        "changes": changes,
    }
