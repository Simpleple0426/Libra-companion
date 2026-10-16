"""Consistent SQLite configuration and transparent database-shard routing."""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from infrastructure.paths import COGNITION_DATABASE_PATH, CONTENT_DATABASE_PATH, DATABASE_PATH

CONTENT_TABLES = {
    'favorite_messages', 'letters', 'shared_moment_comments', 'shared_moments',
    'life_moment_imports',
    'xhs_browse_sessions', 'xhs_notes', 'xhs_search_runs', 'xhs_shared_notes',
}
CORE_TABLES = {
    'todo_reminders',
    'music_chat_requests', 'movie_viewings', 'movie_message_links', 'movie_quotes', 'movie_chat_requests',
    'app_settings', 'calendar_events', 'call_sessions', 'call_turns',
    'checkin_events', 'focus_sessions', 'habit_checkins', 'habits',
    'important_dates', 'libra_attribute_adjustments',
    'libra_attribute_effects', 'libra_attribute_snapshots',
    'libra_state_events', 'libra_thoughts', 'libra_timeline_events',
    'messages', 'mobile_state', 'push_tokens', 'threads', 'todos',
    'user_timeline_events', 'weather_awareness_events', 'work_calendar',
    'world_events',
}
COGNITION_TABLES = {
    'lmc_candidates',
    'life_threads',
    'lmc_memories', 'lmc_event_context', 'lmc_sources', 'lmc_revisions',
    'lmc_search_documents', 'lmc_embeddings', 'lmc_fts', 'lmc_usage_events',
    'lmc_session_recall', 'lmc_recall_logs', 'lmc_memory_coordinates',
    'lmc_memory_relations', 'lmc_relation_jobs', 'lmc_extraction_decisions',
    'lmc_memory_audits', 'lmc_calendar_summaries', 'lmc_calendar_sources',
    'lmc_dream_pages', 'lmc_dream_jobs', 'lmc_dream_usage',
    'lmc_dream_entries',
    'affect_events', 'affect_observations',  'affect_state',
    'canonical_shared_history', 'canonical_shared_history_chunk_embeddings',
    'canonical_shared_history_chunks', 'canonical_shared_history_chunks_fts',
    'canonical_shared_history_embeddings', 'canonical_shared_history_fts',
    'character_corpus_v2', 'character_corpus_v2_embeddings',
    'character_corpus_v2_fts',
    'cognition_actions', 'cognition_call_inputs', 'cognition_context_revisions',
    'cognition_delivery', 'cognition_feedback', 'cognition_inputs',
    'cognition_notifications', 'cognition_post_jobs', 'cognition_turns',
    'cognitive_traces', 'experience_segments', 'llm_usage_events', 'memory_config',
    'memory_jobs', 'raw_experiences', 'segment_experiences', 'memory_stream_boundaries',
}

_ROUTES = {**{name: 'core' for name in CORE_TABLES},
           **{name: 'content' for name in CONTENT_TABLES},
           **{name: 'cognition' for name in COGNITION_TABLES}}
_TABLE_PATTERN = re.compile(
    r'(?<![.\w])(' + '|'.join(sorted(map(re.escape, _ROUTES), key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)
_DML = re.compile(r'^\s*(SELECT|INSERT|UPDATE|DELETE|REPLACE|WITH)\b', re.IGNORECASE)
_SQL_LITERALS = re.compile(r"'(?:''|[^'])*'|--[^\n]*|/\*[\s\S]*?\*/")
_WRITE = re.compile(r'^\s*(INSERT|UPDATE|DELETE|REPLACE)\b', re.IGNORECASE)
_BEGIN = re.compile(r'\s*BEGIN(?:\s+(?:IMMEDIATE|DEFERRED|EXCLUSIVE))?(?:\s+TRANSACTION)?\s*;?\s*', re.IGNORECASE)
_writer_admission = threading.Lock()


def route_sql(sql: str, schemas: dict[str, str] | None = None) -> str:
    if not _DML.match(sql):
        return sql
    if schemas == {}:
        return sql
    schemas = schemas or {'core': 'main', 'content': 'content', 'cognition': 'cognition'}
    protected = [(m.start(), m.end()) for m in _SQL_LITERALS.finditer(sql)]
    def qualify(match):
        if any(start <= match.start() < end for start, end in protected):
            return match.group(0)
        # In SQLite FTS, the left side of MATCH must remain the bare virtual
        # table name; its FROM occurrence is qualified separately.
        if re.match(r'\s+MATCH\b', sql[match.end():], re.IGNORECASE):
            return match.group(1)
        # FTS auxiliary functions require the bare table-name argument too.
        if re.search(r'\b(?:bm25|highlight|snippet)\s*\(\s*$', sql[:match.start()], re.IGNORECASE):
            return match.group(1)
        return schemas[_ROUTES[match.group(1).lower()]] + '.' + match.group(1)
    return _TABLE_PATTERN.sub(qualify, sql)


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    """Inspect the owning shard, or main for standalone/test databases."""
    schemas = getattr(connection, 'route_schemas', {})
    schema = schemas.get(_ROUTES.get(table), 'main')
    if schema not in {'main', 'core', 'content', 'cognition'}:
        raise ValueError('unknown_database_schema')
    return connection.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _retry(operation, *args):
    # SQLite already waits using busy_timeout. Replaying a failed statement
    # multiplies that wait and cannot repair BUSY_SNAPSHOT in its old transaction.
    # In particular, never replay a partially consumed executemany iterator.
    return operation(*args)


class RetryCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        if (self.connection._reserve_writes and not self.connection.in_transaction
                and _BEGIN.fullmatch(sql)):
            self.connection._begin_write()
            return self
        self.connection._prepare_write(sql)
        return _retry(super().execute, route_sql(sql, self.connection.route_schemas), parameters)

    def executemany(self, sql, seq_of_parameters):
        self.connection._prepare_write(sql)
        return _retry(super().executemany, route_sql(sql, self.connection.route_schemas), seq_of_parameters)


class RoutedConnection(sqlite3.Connection):
    route_schemas = {'core': 'main', 'content': 'content', 'cognition': 'cognition'}
    _memory_work_pending = frozenset()
    _reserve_writes = False
    _busy_seconds = 30.0

    def _begin_write(self):
        # Attached databases are opened with different main schemas. Reserve
        # all of them before the first DML, and admit only one reservation at a
        # time, so core->cognition and cognition->core writers cannot deadlock.
        started = time.monotonic()
        if not _writer_admission.acquire(timeout=self._busy_seconds):
            raise sqlite3.OperationalError('database writer admission timed out')
        try:
            remaining = max(0, self._busy_seconds - (time.monotonic() - started))
            super().execute(f'PRAGMA busy_timeout={int(remaining * 1000)}')
            return super().execute('BEGIN IMMEDIATE')
        finally:
            try:
                super().execute(f'PRAGMA busy_timeout={int(self._busy_seconds * 1000)}')
            finally:
                _writer_admission.release()

    def _prepare_write(self, sql):
        if not self._reserve_writes or self.in_transaction:
            return
        statement = _SQL_LITERALS.sub(' ', sql)
        is_write = _WRITE.match(statement) or (
            re.match(r'^\s*WITH\b', statement, re.IGNORECASE)
            and re.search(r'\b(INSERT|UPDATE|DELETE|REPLACE)\b', statement, re.IGNORECASE))
        if is_write:
            self._begin_write()

    def mark_memory_work(self, queue):
        self._memory_work_pending = self._memory_work_pending | {queue}

    def _notify_memory_commit(self):
        if self._memory_work_pending:
            queues = self._memory_work_pending
            self._memory_work_pending = frozenset()
            from infrastructure.memory_wakeup import memory_work_available
            memory_work_available.notify(*queues)

    def cursor(self, factory=RetryCursor):
        return super().cursor(factory)

    def execute(self, sql, parameters=()):
        if (self._reserve_writes and not self.in_transaction
                and _BEGIN.fullmatch(sql)):
            return self._begin_write()
        self._prepare_write(sql)
        return _retry(super().execute, route_sql(sql, self.route_schemas), parameters)

    def executemany(self, sql, seq_of_parameters):
        self._prepare_write(sql)
        return _retry(super().executemany, route_sql(sql, self.route_schemas), seq_of_parameters)

    def commit(self):
        result = _retry(super().commit)
        self._notify_memory_commit()
        return result

    def rollback(self):
        result = super().rollback()
        self._memory_work_pending = frozenset()
        return result

    def close(self):
        self._memory_work_pending = frozenset()
        return super().close()

    def __exit__(self, exc_type, exc_value, traceback):
        # SQLite 的上下文管理器不会经过上面的提交方法，需要在此补发通知。
        try:
            result = super().__exit__(exc_type, exc_value, traceback)
        except BaseException:
            self._memory_work_pending = frozenset()
            raise
        if exc_type is None:
            self._notify_memory_commit()
        else:
            self._memory_work_pending = frozenset()
        return result


def connect(path: str | Path = DATABASE_PATH, *, timeout: float = 30,
            row_factory=sqlite3.Row, attach_shards: bool = True) -> sqlite3.Connection:
    path = Path(path).resolve()
    known_paths = {
        DATABASE_PATH.resolve(), CONTENT_DATABASE_PATH.resolve(),
        COGNITION_DATABASE_PATH.resolve(),
    }
    # Temporary/test/backup databases are deliberately self-contained.  This
    # prevents a unit test using tmp_path from attaching and mutating live data.
    if path not in known_paths:
        attach_shards = False
    connection = sqlite3.connect(path, timeout=timeout, factory=RoutedConnection)
    try:
        connection.route_schemas = {
            'core': 'main' if path == DATABASE_PATH.resolve() else 'core',
            'content': 'main' if path not in known_paths or path == CONTENT_DATABASE_PATH.resolve() else 'content',
            'cognition': 'main' if path not in known_paths or path == COGNITION_DATABASE_PATH.resolve() else 'cognition',
        }
        if path not in known_paths:
            connection.route_schemas = {}
        connection.row_factory = row_factory
        connection._busy_seconds = max(0.0, float(timeout))
        connection.execute(f'PRAGMA busy_timeout={int(connection._busy_seconds * 1000)}')
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA synchronous=NORMAL')
        if attach_shards:
            attachments = []
            if path != DATABASE_PATH.resolve():
                attachments.append(('core', DATABASE_PATH))
            if path != CONTENT_DATABASE_PATH.resolve():
                attachments.append(('content', CONTENT_DATABASE_PATH))
            if path != COGNITION_DATABASE_PATH.resolve():
                attachments.append(('cognition', COGNITION_DATABASE_PATH))
            for schema, shard in attachments:
                connection.execute(f'ATTACH DATABASE ? AS {schema}', (str(shard),))
                connection.execute(f'PRAGMA {schema}.journal_mode=WAL')
                connection.execute(f'PRAGMA {schema}.synchronous=NORMAL')
        connection._reserve_writes = attach_shards
        return connection
    except BaseException:
        connection.close()
        raise



@contextmanager
def write_transaction(connection: sqlite3.Connection, *, immediate: bool = True):
    """Keep the lock boundary explicit and limited to database work only."""
    connection.execute('BEGIN IMMEDIATE' if immediate else 'BEGIN')
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
