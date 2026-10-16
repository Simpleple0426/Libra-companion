"""Read-only HTTP smoke check; no model calls or user data are printed."""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def check(base_url: str, timeout: float = 15, *, integrity: bool = False) -> list[dict]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    endpoints = ["/health?check_integrity=true" if integrity else "/health", "/", "/openapi.json", "/life-system/status", "/room-media/movies"]
    results = []
    for endpoint in endpoints:
        try:
            details = {}
            with opener.open(base_url.rstrip("/") + endpoint, timeout=timeout) as response:
                payload = json.load(response)
                if endpoint.startswith("/health"):
                    valid = payload.get("healthy") is True
                elif endpoint == "/openapi.json":
                    paths = payload.get("paths", {})
                    valid = all(path in paths for path in ("/health", "/chat", "/life-system/status"))
                elif endpoint == "/room-media/movies":
                    valid = isinstance(payload.get("movies"), list)
                elif endpoint == "/life-system/status":
                    disabled = payload.get("mode") == "disabled"
                    scheduler = payload.get("scheduler") or {}
                    details = {"life_status": payload.get("status"),
                               "worker_active": bool(scheduler.get("worker_active")),
                               "scheduler_blocked": bool(scheduler.get("blocker"))}
                    valid = payload.get("success") is True and (disabled or (
                        payload.get("status") == "ready" and details["worker_active"]
                        and not details["scheduler_blocked"] and not scheduler.get("status_read_error")))
                else:
                    valid = payload.get("message") == "Libra Companion backend is running"
                results.append({"endpoint": endpoint, "status": response.status, "ok": valid, **details})
        except (OSError, ValueError, AttributeError, urllib.error.URLError) as error:
            results.append({"endpoint": endpoint, "ok": False, "error": type(error).__name__})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--integrity", action="store_true", help="Also run SQLite integrity checks")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    results = check(args.url, args.timeout, integrity=args.integrity)
    print(json.dumps(results, indent=2))
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
