"""Transactional migration from development-stage names to life-domain names."""
import sqlite3
from contextlib import closing
from pathlib import Path

TABLE_RENAMES = {
    'p2_meta': 'life_cognition_state',
    'p2_observations': 'life_observations',
    'p2_memories': 'life_memories',
    'p2_calls': 'life_model_calls',
    'p2_runs': 'life_cognition_runs',
    'p2_updates': 'life_observation_updates',
    'p2_retrievals': 'life_memory_retrievals',
    'p2_artifacts': 'life_cognition_artifacts',
    'p2_transport_attempts': 'life_model_transport_attempts',
    'p3_meta': 'life_interaction_config',
    'p3_messages': 'life_received_messages',
    'p3_ticks': 'life_sleep_ticks',
    'p3_replies': 'life_interaction_replies',
    'p3_chat_memory': 'life_message_archive',
    'p4_meta': 'life_scheduler_state',
    'p4_jobs': 'life_scheduler_jobs',
    'p4_attempts': 'life_scheduler_attempts',
    'p4_inbox': 'life_scheduler_inbox',
    'p4_records': 'life_scheduler_logs',
    'p4_recoveries': 'life_scheduler_recoveries',
    'p4_signals': 'life_scheduler_signals',
}


def migrate(path):
    """Rename existing tables atomically; never merge conflicting namespaces."""
    path = Path(path)
    if not path.is_file():
        return {}
    with closing(sqlite3.connect(path, timeout=20)) as db, db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not tables.intersection(TABLE_RENAMES):
            return {}
        db.execute('BEGIN IMMEDIATE')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        changes = {old: new for old, new in TABLE_RENAMES.items() if old in tables}
        for old, new in changes.items():
            if new in tables:
                raise ValueError(f'life table migration conflict: {old} and {new}')
        for old, new in changes.items():
            db.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
        return changes
