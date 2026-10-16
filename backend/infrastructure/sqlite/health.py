"""Health and ownership checks for Libra's SQLite shards."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from infrastructure.paths import (
    COGNITION_DATABASE_PATH,
    CONTENT_DATABASE_PATH,
    DATABASE_PATH,
)
from infrastructure.sqlite.connection import CORE_TABLES, COGNITION_TABLES, CONTENT_TABLES



SHARD_PATHS = {
    "core": DATABASE_PATH,
    "content": CONTENT_DATABASE_PATH,
    "cognition": COGNITION_DATABASE_PATH,
}


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)


def _tables(path: Path) -> set[str]:
    with _connect_read_only(path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }


def shard_health(*, check_integrity: bool = False) -> dict[str, object]:
    existing = {name: _tables(path) for name, path in SHARD_PATHS.items()}
    expected = {
        "core": set(CORE_TABLES),
        "content": set(CONTENT_TABLES),
        "cognition": set(COGNITION_TABLES),
    }
    missing = {name: sorted(expected[name] - existing[name]) for name in expected}
    misplaced = sorted(
        existing["core"] & (set(CONTENT_TABLES) | set(COGNITION_TABLES))
    )
    cross_shard = {
        "content": sorted(existing["content"] & set(COGNITION_TABLES)),
        "cognition": sorted(existing["cognition"] & set(CONTENT_TABLES)),
    }
    files: dict[str, dict[str, object]] = {}
    integrity_ok = True
    for name, path in SHARD_PATHS.items():
        item: dict[str, object] = {
            "path": str(path),
            "size": path.stat().st_size,
            "table_count": len(existing[name]),
        }
        if check_integrity:
            with _connect_read_only(path) as connection:
                integrity = str(
                    connection.execute("PRAGMA integrity_check").fetchone()[0]
                )
            item["integrity"] = integrity
            integrity_ok = integrity_ok and integrity == "ok"
        files[name] = item
    healthy = (
        integrity_ok
        and not any(missing.values())
        and not misplaced
        and not any(cross_shard.values())
    )
    return {
        "healthy": healthy,
        "files": files,
        "missing": missing,
        "misplaced_in_core": misplaced,
        "unexpected_cross_shard": cross_shard,
    }


def validate_database_shards() -> None:
    report = shard_health()
    if not report["healthy"]:
        raise RuntimeError(f"database shard validation failed: {report}")
