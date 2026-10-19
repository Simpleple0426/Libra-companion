"""Compact historical cognition snapshots without touching chat or memory data."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from application.turn_pipeline import stored_context_json
from infrastructure.paths import COGNITION_DATABASE_PATH
from infrastructure.sqlite.connection import connect


def run():
    before = Path(COGNITION_DATABASE_PATH).stat().st_size
    changed = 0
    with connect(COGNITION_DATABASE_PATH, attach_shards=False) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for table, identity, column in (
            ('cognition_turns', 'turn_id', 'context_json'),
            ('cognition_context_revisions', 'rowid', 'snapshot_json'),
        ):
            rows = connection.execute(f'SELECT {identity},{column} FROM {table}').fetchall()
            for row in rows:
                try:
                    compacted = stored_context_json(json.loads(row[column]))
                except (TypeError, json.JSONDecodeError):
                    continue
                if compacted != row[column]:
                    connection.execute(
                        f'UPDATE {table} SET {column}=? WHERE {identity}=?',
                        (compacted, row[identity]),
                    )
                    changed += 1
        connection.execute(
            'DELETE FROM cognition_context_revisions WHERE revision < '
            '(SELECT MAX(newer.revision) FROM cognition_context_revisions newer '
            'WHERE newer.turn_id=cognition_context_revisions.turn_id)'
        )
        connection.commit()
    with connect(COGNITION_DATABASE_PATH, attach_shards=False) as connection:
        connection.execute('VACUUM')
    after = Path(COGNITION_DATABASE_PATH).stat().st_size
    return {'changed_rows': changed, 'before_bytes': before, 'after_bytes': after}


if __name__ == '__main__':
    print({**run(), 'database': str(COGNITION_DATABASE_PATH)})
