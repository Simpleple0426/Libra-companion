"""Retrieve authored story history; lived memories use the shared LMC entrypoint."""
from __future__ import annotations


class SharedHistoryStore:
    def __init__(self, canonical_store):
        self.canonical_store = canonical_store

    def read_excerpt(self, chunk_id: str) -> dict:
        """Read one indexed source fragment, never an arbitrary file path."""
        with self.canonical_store.connect() as connection:
            row = connection.execute(
                'SELECT chunk_id,source_path,line_start,line_end,content '
                'FROM canonical_shared_history_chunks WHERE chunk_id=?', (chunk_id,)).fetchone()
        if row is None:
            raise ValueError('unknown_history_excerpt')
        return {'chunk_id': row['chunk_id'], 'source_path': row['source_path'],
                'line_start': row['line_start'], 'line_end': row['line_end'],
                'transcript_excerpt': row['content']}

    def context_for(self, query: str, *, thread_id=None, recent_messages=(), budget=7600, query_plan=None) -> str:
        options = {'query_plan': query_plan} if query_plan is not None else {}
        return self.canonical_store.context_for(
            query, limit=5, budget=max(1000, int(budget)), **options
        )
