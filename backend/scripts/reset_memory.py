"""Explicit local memory reset. Chat, persona, world and affect data are retained."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domains.memory.store import MemoryStore, utc
from infrastructure.paths import COGNITION_DATABASE_PATH

LEGACY = {
    'memory_records', 'episode_details', 'entities', 'memory_entities', 'memory_sources',
    'memory_revisions', 'memory_lifecycles', 'memory_strength_events', 'memory_usage_events',
    'episode_search_documents', 'memory_recall_logs', 'memory_session_recall', 'episode_embeddings',
    'episode_fts', 'memory_calendar_summaries', 'memory_calendar_sources', 'memory_dependencies',
    'semantic_details', 'relationship_details', 'self_details', 'story_details', 'story_members',
    'episode_links', 'open_loops', 'reflection_details', 'memory_reinforcement_receipts',
    'lmc_coordinates', 'lmc_relations', 'lmc_jobs', 'lmc_candidate_decisions', 'lmc_audits',
    'user_memories', 'long_term_memories',
    'conversation_segments', 'segment_streams',
}
CURRENT = {
    'raw_experiences', 'experience_segments', 'segment_experiences', 'memory_stream_boundaries',
    'memory_jobs', 'cognitive_traces', 'lmc_candidates', 'lmc_memories', 'lmc_event_context', 'lmc_sources',
    'lmc_revisions', 'lmc_usage_events', 'lmc_recall_logs', 'lmc_memory_coordinates',
    'lmc_memory_relations', 'lmc_relation_jobs', 'lmc_extraction_decisions', 'lmc_memory_audits',
    'lmc_search_documents', 'lmc_embeddings', 'lmc_fts', 'lmc_session_recall',
    'lmc_calendar_summaries', 'lmc_calendar_sources',
    'lmc_dream_pages', 'lmc_dream_jobs', 'lmc_dream_usage',
    'lmc_dream_entries',
}


def reset(path, *, apply=False):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('database_not_found')
    with sqlite3.connect(path) as c:
        tables = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        affected = (LEGACY | CURRENT) & tables
        before = {name: c.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in sorted(affected)}
        if not apply:
            return {'database': str(path), 'apply': False, 'counts': before}
        c.execute('PRAGMA foreign_keys=OFF')
        c.execute('BEGIN IMMEDIATE')
        now = utc()
        try:
            c.execute("DELETE FROM memory_config WHERE key='dream_requested'")
            for name in sorted(LEGACY & tables):
                c.execute(f'DROP TABLE "{name}"')
            for name in sorted(CURRENT & tables):
                c.execute(f'DROP TABLE "{name}"')
            c.execute("DELETE FROM memory_config WHERE key LIKE 'segment_progress:%' OR key IN ('lmc_native_migrated','lmc_maintained_at','calendar_summary_signature','main_thread_id','previous_main_thread_id','daily_thread_handoff')")
            for key, value in (('memory_reset_at', now), ('start_fresh_thread', '1')):
                c.execute('INSERT INTO memory_config VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
            if 'cognition_post_jobs' in tables:
                c.execute("UPDATE cognition_post_jobs SET status='completed' WHERE status='pending'")
            c.commit()
        except Exception:
            c.rollback()
            raise
    store = MemoryStore(path)
    store.initialize()
    with store.connect() as c:
        remaining = {name: c.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in CURRENT}
    if any(remaining.values()):
        raise RuntimeError('memory_reset_verification_failed')
    return {'database': str(path), 'apply': True, 'reset_at': now, 'cleared_rows': sum(before.values()),
            'dropped_legacy_tables': sorted(LEGACY & tables), 'remaining': remaining}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, default=COGNITION_DATABASE_PATH)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(reset(args.database, apply=args.apply), ensure_ascii=False, indent=2))
