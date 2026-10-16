import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from application.tool_execution import remaining_timeout
from infrastructure.paths import ENV_PATH
from dotenv import load_dotenv

from astral import LocationInfo
from astral.sun import sun


_CACHE_SECONDS = 30 * 60
_cache: dict[tuple[float, float], tuple[float, dict]] = {}
_TIMEZONE = ZoneInfo("Asia/Shanghai")
_WEATHER_REMINDER_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "prompts" / "weather_reminder.md"
)


def _daylight_info(latitude: float, longitude: float) -> dict:
    location = LocationInfo(
        name="current",
        region="China",
        timezone="Asia/Shanghai",
        latitude=latitude,
        longitude=longitude,
    )
    now = datetime.now(_TIMEZONE)
    solar = sun(location.observer, date=now.date(), tzinfo=_TIMEZONE)
    sunrise = solar["sunrise"]
    sunset = solar["sunset"]
    return {
        "sunrise": sunrise.isoformat(),
        "sunset": sunset.isoformat(),
        "is_daytime": sunrise <= now < sunset,
    }


def _load_local_environment() -> None:
    load_dotenv(ENV_PATH, override=False)


def _load_weather_reminder_prompt() -> str:
    return _WEATHER_REMINDER_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _api_key() -> str:
    _load_local_environment()
    key = os.environ.get("AMAP_MAPS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("后端尚未配置高德 Key")
    return key


def _request(path: str, parameters: dict[str, str]) -> dict:
    query = urlencode({**parameters, "key": _api_key()})
    with urlopen(f"https://restapi.amap.com{path}?{query}", timeout=remaining_timeout(15)) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("status") != "1":
        raise RuntimeError(data.get("info") or "高德服务暂时不可用")
    return data


def _text(value) -> str:
    if isinstance(value, str):
        return value
    return ""


def _integer(value) -> int:
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return 0


def _fallback_reminder(current: str, is_daytime: bool = True) -> str:
    """Return a reliable note when the reminder model is unavailable."""
    if "雷" in current:
        return "外面在打雷，先别急着出门，等天气缓一缓。"
    if any(word in current for word in ("暴雨", "大雨")):
        return "雨势不小，伞要带好，也尽量绕开积水。"
    if "雨" in current:
        return "外面在下雨，伞带好，路上慢一点。"
    if any(word in current for word in ("暴雪", "大雪")):
        return "雪下得有点大，出门当心路滑。"
    if "雪" in current:
        return "外面在下雪，走路时小心一点。"
    if any(word in current for word in ("沙尘", "扬沙", "浮尘")):
        return "外面风沙有点大，戴好口罩再出门。"
    if "霾" in current:
        return "外面有霾，出门记得戴好口罩。"
    if "雾" in current:
        return "外面有雾，视线不太好，路上慢一点。"
    if "风" in current:
        return "外面风有点大，随身的东西记得拿稳。"
    if any(word in current for word in ("晴", "少云")):
        return (
            "外面天气很好，适合出去走走。"
            if is_daytime
            else "夜里天很晴，抬头也许能看见月亮。"
        )
    if "阴" in current:
        return "夜里的云有些厚，天色显得更深了。" if not is_daytime else "今天天色有点沉。"
    if "多云" in current:
        return "夜里云有点多，夜色也显得更沉了。" if not is_daytime else "今天云有点多，天气还算安稳。"
    return f"现在是{current}，出门前看一眼窗外就好。" if current else "出门前看一眼窗外就好。"


def _is_grounded_reminder(
    current: str,
    reminder: str,
    *,
    is_late_night: bool = False,
) -> bool:
    """Reject advice that assumes facts absent from the current condition."""
    unsupported_groups = (
        (("雨",), ("伞", "积水", "淋雨", "雨水")),
        (("雪",), ("雪", "结冰")),
        (("雷",), ("打雷", "闪电", "雷声")),
        (("雾", "霾", "沙尘", "扬沙", "浮尘"), ("口罩", "空气差", "空气不佳")),
        (("风",), ("风大", "大风", "拿稳", "吹走")),
    )
    for evidence, claims in unsupported_groups:
        if not any(token in current for token in evidence) and any(
            claim in reminder for claim in claims
        ):
            return False

    temperature_claims = (
        "着凉",
        "保暖",
        "添衣",
        "多穿",
        "很冷",
        "很热",
        "炎热",
        "凉快",
        "补水",
        "防晒",
        "开窗",
    )
    if any(claim in reminder for claim in temperature_claims):
        return False
    if is_late_night and any(
        phrase in reminder
        for phrase in ("出门", "出去", "散步", "闲逛", "走走")
    ):
        return False
    return True


def _reminder(current: str, local_time: datetime, is_daytime: bool) -> str:
    """Generate one natural note using only the current weather condition."""
    if not current:
        return _fallback_reminder(current, is_daytime)

    _load_local_environment()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not api_key:
        return _fallback_reminder(current, is_daytime)

    base_url = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "deepseek-chat").strip()
    try:
        system_prompt = _load_weather_reminder_prompt()
    except OSError as error:
        print(f"[libra] weather reminder prompt unavailable: {error}")
        return _fallback_reminder(current, is_daytime)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"当前天气：{current}\n"
                    f"当地时间：{local_time.strftime('%H:%M')}\n"
                    f"昼夜状态：{'day' if is_daytime else 'night'}"
                ),
            },
        ],
        "max_tokens": 80,
        "temperature": 0.9,
        "stream": False,
    }
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )
    try:
        # The homepage prefers the model wording, but weather itself must not
        # wait behind a saturated model service for too long.
        timeout_seconds = max(
            1.0,
            min(15.0, float(os.environ.get("WEATHER_LLM_TIMEOUT_SECONDS", "6"))),
        )
        with urlopen(request, timeout=remaining_timeout(timeout_seconds)) as response:
            result = json.loads(response.read().decode("utf-8"))
        reminder = str(result["choices"][0]["message"]["content"]).strip()
        reminder = re.sub(r"^```(?:text)?|```$", "", reminder, flags=re.IGNORECASE).strip()
        reminder = reminder.strip('"\'“”‘’')
        reminder = re.sub(r"\s+", "", reminder)
        if (
            not reminder
            or len(reminder) > 32
            or "\n" in reminder
            or not _is_grounded_reminder(
                current,
                reminder,
                is_late_night=local_time.hour >= 22 or local_time.hour < 6,
            )
        ):
            raise ValueError("天气提醒格式不合要求")
        return reminder
    except Exception as error:
        print(f"[libra] weather reminder LLM failed: {error}")
        return _fallback_reminder(current, is_daytime)


def get_weather(
    latitude: float,
    longitude: float,
    *,
    force_refresh: bool = False,
    include_reminder: bool = True,
) -> dict:
    cache_key = (round(latitude, 2), round(longitude, 2))
    cached = _cache.get(cache_key)
    if not force_refresh and cached and time.time() - cached[0] < _CACHE_SECONDS:
        return {**cached[1], **_daylight_info(latitude, longitude)}

    location = f"{longitude:.6f},{latitude:.6f}"
    reverse = _request(
        "/v3/geocode/regeo",
        {"location": location, "extensions": "base", "radius": "1000"},
    )
    component = reverse.get("regeocode", {}).get("addressComponent", {})
    province = _text(component.get("province"))
    city = _text(component.get("city")) or province
    district = _text(component.get("district"))
    adcode = _text(component.get("adcode"))
    if not city or not district or not adcode:
        raise RuntimeError("高德没有识别出当前市区")

    live_response = _request("/v3/weather/weatherInfo", {"city": adcode, "extensions": "base"})
    forecast_response = _request("/v3/weather/weatherInfo", {"city": adcode, "extensions": "all"})
    lives = live_response.get("lives") or []
    forecasts = forecast_response.get("forecasts") or []
    casts = forecasts[0].get("casts", []) if forecasts else []
    if not lives or len(casts) < 2:
        raise RuntimeError("高德没有返回完整天气数据")

    live = lives[0]
    tomorrow = casts[1]
    day_weather = _text(tomorrow.get("dayweather"))
    night_weather = _text(tomorrow.get("nightweather"))
    if night_weather and night_weather != day_weather:
        tomorrow_weather = f"白天{day_weather}，夜间{night_weather}"
    else:
        tomorrow_weather = f"全天{day_weather}"
    minimum = _integer(tomorrow.get("nighttemp"))
    maximum = _integer(tomorrow.get("daytemp"))
    current = _text(live.get("weather"))
    temperature = _integer(live.get("temperature"))

    daylight = _daylight_info(latitude, longitude)
    data = {
        "city": city,
        "district": district,
        "temperature": temperature,
        "current_weather": current,
        "tomorrow_weather": tomorrow_weather,
        "tomorrow_min": min(minimum, maximum),
        "tomorrow_max": max(minimum, maximum),
        **daylight,
    }
    if include_reminder:
        data["reminder"] = _reminder(
            current,
            datetime.now(_TIMEZONE),
            daylight["is_daytime"],
        )
        _cache[cache_key] = (time.time(), data)
    else:
        data["reminder"] = _fallback_reminder(current, daylight["is_daytime"])
    return data
