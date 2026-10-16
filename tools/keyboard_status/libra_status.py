"""Read a three-value Libra status over HTTP/Tailscale.

This module is intentionally independent from the Libra backend. Copy this
directory to the keyboard computer, then import ``get_libra_status`` from the
existing image-switching program.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable


VALID_STATUSES = frozenset({"上班", "法院", "悠闲"})


class LibraStatusUnavailable(RuntimeError):
    """Raised when the Libra computer cannot provide a usable status."""


def derive_status(
    life_payload: dict[str, Any],
) -> str:
    """Reduce Libra's current activity to one status for the keyboard image."""
    if "current" in life_payload:
        # Accept snapshots from older deployments as well.
        current = life_payload.get("current") or {}
        working = current.get("state_type") == "working"
        place = str(current.get("from_location") or "")
    else:
        if life_payload.get("status") != "ready":
            raise LibraStatusUnavailable("生活引擎尚未就绪")
        activity = life_payload.get("activity") or {}
        working = activity.get("kind") == "work" and activity.get("status") == "running"
        place = str(life_payload.get("place_name") or "")
    if not working:
        return "悠闲"
    if "法院" in place:
        return "法院"
    return "上班"


def _read_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "libra-keyboard-status/1"},
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise LibraStatusUnavailable(f"无法读取 {url}: {error}") from error
    if not isinstance(payload, dict):
        raise LibraStatusUnavailable(f"接口返回的不是 JSON 对象：{url}")
    return payload


def get_libra_status(
    base_url: str,
    *,
    timeout: float = 5.0,
    reader: Callable[[str, float], dict[str, Any]] = _read_json,
) -> str:
    """Fetch the current status from a Libra backend reachable by Tailscale."""
    base_url = base_url.strip().rstrip("/")
    if not base_url:
        raise ValueError("base_url 不能为空")
    life = reader(f"{base_url}/life-system/status", timeout)
    return derive_status(life)
