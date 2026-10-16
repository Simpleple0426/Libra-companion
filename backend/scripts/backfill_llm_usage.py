"""Backfill Codex token usage events from rollout JSONL files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from infrastructure.sqlite.database import init_database, save_llm_usage_event
from infrastructure.paths import ENV_PATH


def _local_day(timestamp: str) -> str:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone().date().isoformat()


def backfill(day: str) -> tuple[int, int]:
    load_dotenv(ENV_PATH, override=False)
    init_database()
    codex_home = Path(os.environ.get("LIBRA_CODEX_HOME", Path.home() / ".codex")).expanduser()
    session_root = codex_home / "sessions"
    inserted = 0
    found = 0
    model = os.environ.get("LIBRA_LLM_MODEL", "").strip()

    for path in session_root.rglob("*.jsonl"):
        thread_id = None
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload") or {}
                if event.get("type") == "session_meta":
                    thread_id = payload.get("id") or thread_id
                    continue
                if event.get("type") != "event_msg" or payload.get("type") != "token_count":
                    continue
                info = payload.get("info") or {}
                usage = info.get("last_token_usage") or {}
                timestamp = str(event.get("timestamp") or "")
                if not timestamp or _local_day(timestamp) != day:
                    continue
                input_tokens = int(usage.get("input_tokens") or 0)
                output_tokens = int(usage.get("output_tokens") or 0)
                if input_tokens <= 0 and output_tokens <= 0:
                    continue
                found += 1
                key_material = f"rollout|{path.resolve()}|{line_number}|{timestamp}"
                event_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
                if save_llm_usage_event(
                    event_key=event_key,
                    occurred_at=timestamp,
                    provider="codex",
                    model=model,
                    thread_id=thread_id,
                    source="historical_call",
                    input_tokens=input_tokens,
                    cached_input_tokens=int(usage.get("cached_input_tokens") or 0),
                    output_tokens=output_tokens,
                    reasoning_output_tokens=int(usage.get("reasoning_output_tokens") or 0),
                    total_tokens=int(usage.get("total_tokens") or input_tokens + output_tokens),
                    context_window=int(info.get("model_context_window") or 0) or None,
                    imported_from=str(path),
                ):
                    inserted += 1
    return found, inserted


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Local date, YYYY-MM-DD")
    args = parser.parse_args()
    found_count, inserted_count = backfill(args.date)
    print(f"found={found_count} inserted={inserted_count}")
