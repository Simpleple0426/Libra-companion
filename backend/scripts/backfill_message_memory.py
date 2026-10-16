"""Idempotently feed legacy delivered chat history into Memory V2."""
import argparse
import json
import sqlite3
from pathlib import Path

from application.memory_segmentation import drain_segments
from domains.memory.store import MemoryStore, dumps, uid, utc
from infrastructure.paths import DATABASE_PATH


ALLOWED_SOURCES = (
    'chat', 'proactive', 'emotion_impulse', 'habit_review',
    'weather_awareness', 'todo_review', 'user_timeline_update',
    'user_status_update', 'xhs_discovery',
)
ALLOWED_TYPES = ('text', 'voice')


def eligible(connection):
    reset = connection.execute("SELECT value FROM memory_config WHERE key='memory_reset_at'").fetchone()
    cutoff = reset[0] if reset else None
    source_marks = ','.join('?' for _ in ALLOWED_SOURCES)
    type_marks = ','.join('?' for _ in ALLOWED_TYPES)
    rows = connection.execute(f'''
        SELECT m.* FROM messages m
        WHERE m.source IN ({source_marks})
          AND m.message_type IN ({type_marks})
          AND trim(m.content) != ''
          AND NOT EXISTS (
              SELECT 1 FROM raw_experiences r
              WHERE r.source_system='libra_chat' AND r.source_id=CAST(m.id AS TEXT)
          )
        ORDER BY m.id
    ''', (*ALLOWED_SOURCES, *ALLOWED_TYPES)).fetchall()
    return [row for row in rows if cutoff is None or utc(row['created_at']) > cutoff]


def backfill(path: Path, *, apply=False):
    store = MemoryStore(path)
    store.initialize()
    with store.connect() as connection:
        rows = eligible(connection)
    summary = {
        'eligible': len(rows),
        'first_message_id': rows[0]['id'] if rows else None,
        'last_message_id': rows[-1]['id'] if rows else None,
        'inserted': 0,
        'segmented': 0,
    }
    if not apply or not rows:
        return summary
    # Historical messages do not store their original provider session.
    thread_id = None
    with store.connect(True) as connection:
        # 历史消息会排在当前消息之后，先登记边界，避免混入当前候选话题。
        now = utc()
        cutoff = connection.execute('SELECT COALESCE(MAX(rowid),0) FROM raw_experiences').fetchone()[0]
        connection.execute('INSERT OR IGNORE INTO memory_stream_boundaries VALUES (?,?,?,?,0)',
                           ('chat', cutoff, 'historical_backfill_boundary', now))
        for row in rows:
            occurred_at = utc(row['created_at'])
            connection.execute('''INSERT INTO raw_experiences
                (experience_id,source_type,source_system,source_id,thread_id,actor,
                 content,occurred_at,ingested_at,metadata_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)''', (
                    uid('rx'), 'chat_message', 'libra_chat', str(row['id']),
                    thread_id, 'libra' if row['role'] == 'assistant' else row['role'], row['content'], occurred_at, now,
                    dumps({'message_id': row['id'], 'historical_backfill': True,
                           'original_source': row['source'],
                           'original_message_type': row['message_type']}),
                ))
        summary['inserted'] = len(rows)
    while True:
        count = drain_segments(store, force=True)
        if count < 200:
            break
    with store.connect() as connection:
        summary['segmented'] = connection.execute(
            "SELECT COUNT(*) FROM raw_experiences "
            "WHERE json_extract(metadata_json,'$.historical_backfill')=1 AND segmented=1"
        ).fetchone()[0]
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path,
                        default=DATABASE_PATH)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(backfill(args.database, apply=args.apply), ensure_ascii=False))
