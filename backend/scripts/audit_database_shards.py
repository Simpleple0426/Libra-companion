"""Audit the three Libra SQLite shards without modifying them."""
from __future__ import annotations

import json
from infrastructure.sqlite.health import shard_health


if __name__ == "__main__":
    print(json.dumps(shard_health(check_integrity=True), ensure_ascii=False, indent=2))
