"""Explicit, allowlisted retirement of pre-V1 stores. Never runs at startup."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from infrastructure.paths import DATABASE_PATH, BACKUP_ROOT

TABLES = ('canon_samples_fts', 'canon_imports', 'canon_samples',
          'emotional_events', 'emotional_state', 'user_memories', 'long_term_memories')
RETIRED_SETTING_KEYS = ('daily_memory_attempt_hour', 'daily_memory_date',
                       'emotion_impulse_fingerprint', 'emotion_impulse_reviewed_at',
                       'emotion_impulse_sent_at', 'emotion_last_ambient_key',
                       'memory_extraction_message_id')
TARGETS = (DATABASE_PATH, BACKUP_ROOT / 'libra_20260902_125426.db')


def retained_digest(connection):
    result = {}
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        if name in TABLES or name.startswith('canon_samples_fts_') or name == 'sqlite_sequence':
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        rows = connection.execute('SELECT * FROM ' + quoted).fetchall()
        if name == 'app_settings':
            rows = [row for row in rows if row[0] not in RETIRED_SETTING_KEYS]
        serialized = sorted(repr(row) for row in rows)
        result[name] = (len(rows), hashlib.sha256('\n'.join(serialized).encode()).hexdigest())
    return result


def clean(path, apply=False):
    path = Path(path).resolve(strict=True)
    connection = sqlite3.connect(path.as_uri() + '?mode=' + ('rw' if apply else 'ro'), uri=True, timeout=10)
    try:
        existing = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {name: connection.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]
                  for name in TABLES if name in existing}
        keys = [row[0] for row in connection.execute('SELECT key FROM app_settings')
                if row[0] in RETIRED_SETTING_KEYS] if 'app_settings' in existing else []
        if not apply:
            return {'database': str(path), 'old_rows': counts, 'retired_settings': keys}
        connection.execute('PRAGMA secure_delete=ON')
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN EXCLUSIVE')
        try:
            before = retained_digest(connection)
            fk_before = set(connection.execute('PRAGMA foreign_key_check').fetchall())
            for name in TABLES:
                connection.execute('DROP TABLE IF EXISTS "' + name + '"')
            if 'app_settings' in existing:
                connection.executemany('DELETE FROM app_settings WHERE key=?', [(key,) for key in keys])
            if retained_digest(connection) != before:
                raise RuntimeError('Retained data changed')
            if set(connection.execute('PRAGMA foreign_key_check').fetchall()) - fk_before:
                raise RuntimeError('New foreign-key violation')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        connection.execute('VACUUM')
        checkpoint = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if checkpoint[0]:
            raise RuntimeError('WAL checkpoint busy; stop database clients and retry')
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Integrity check failed')
        if retained_digest(connection) != before:
            raise RuntimeError('Post-vacuum retained data differs')
        return {'database': str(path), 'deleted_old_rows': counts, 'deleted_settings': keys,
                'retained_tables_verified': len(before)}
    finally:
        connection.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    for target in TARGETS:
        if not target.exists():
            continue
        resolved = target.resolve(strict=True)
        if resolved != target.absolute() or resolved.parent not in {DATABASE_PATH.parent, BACKUP_ROOT}:
            raise RuntimeError('Unexpected database target')
        print(json.dumps(clean(resolved, args.apply), ensure_ascii=False))
