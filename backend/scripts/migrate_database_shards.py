"""One-time, restart-safe migration from libra.db to content/cognition shards."""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from infrastructure.paths import BACKUP_ROOT, COGNITION_DATABASE_PATH, CONTENT_DATABASE_PATH, DATABASE_PATH
from infrastructure.sqlite.connection import COGNITION_TABLES, CONTENT_TABLES


def _application_tables(connection):
    return {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )}


def _prune(path: Path, keep: set[str]) -> None:
    connection = sqlite3.connect(path, timeout=30)
    try:
        connection.execute('PRAGMA foreign_keys=OFF')
        virtual = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE 'CREATE VIRTUAL TABLE%'"
        )}
        expanded_keep = set(keep)
        for virtual_name in virtual & keep:
            expanded_keep.update(
                name for name in _application_tables(connection)
                if name.startswith(virtual_name + '_')
            )
        # Dropping a virtual table removes its own FTS shadow tables.
        for name in sorted(virtual - keep):
            connection.execute(f'DROP TABLE IF EXISTS "{name}"')
        for name in sorted(_application_tables(connection) - expanded_keep):
            connection.execute(f'DROP TABLE IF EXISTS "{name}"')
        connection.commit()
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA synchronous=NORMAL')
        connection.execute('VACUUM')
    finally:
        connection.close()


def _remove_cross_database_foreign_keys() -> None:
    """SQLite foreign keys cannot reference a table in an attached database."""
    connection = sqlite3.connect(COGNITION_DATABASE_PATH, timeout=30)
    try:
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('ALTER TABLE cognition_inputs RENAME TO cognition_inputs_legacy')
        connection.execute('''CREATE TABLE cognition_inputs (
            request_key TEXT PRIMARY KEY,
            payload_hash TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )''')
        connection.execute('''INSERT INTO cognition_inputs
            (request_key,payload_hash,message_id,created_at)
            SELECT request_key,payload_hash,message_id,created_at
            FROM cognition_inputs_legacy''')
        connection.execute('DROP TABLE cognition_inputs_legacy')
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def migrate() -> None:
    if CONTENT_DATABASE_PATH.exists() or COGNITION_DATABASE_PATH.exists():
        raise RuntimeError('Shard database already exists; refusing to overwrite it.')
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = BACKUP_ROOT / f'libra_before_sharding_{stamp}.db'
    source = sqlite3.connect(DATABASE_PATH, timeout=30)
    try:
        source.execute('PRAGMA busy_timeout=30000')
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    shutil.copy2(backup, CONTENT_DATABASE_PATH)
    shutil.copy2(backup, COGNITION_DATABASE_PATH)
    _prune(CONTENT_DATABASE_PATH, CONTENT_TABLES)
    _prune(COGNITION_DATABASE_PATH, COGNITION_TABLES)
    _remove_cross_database_foreign_keys()
    # Core is pruned last. A failure before this point leaves the original intact.
    core = sqlite3.connect(DATABASE_PATH)
    try:
        core_keep = _application_tables(core) - CONTENT_TABLES - COGNITION_TABLES
    finally:
        core.close()
    _prune(DATABASE_PATH, core_keep)
    print(f'Migrated database shards; backup={backup}')


if __name__ == '__main__':
    migrate()
