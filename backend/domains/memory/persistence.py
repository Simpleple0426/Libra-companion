"""Database lifecycle, schema migration and search/vector indexing."""
from .base import *  # shared domain primitives


class MemoryPersistenceMixin:
    def __init__(self, path, embedding_adapter: EmbeddingAdapter | None = None,
                 query_expander=None, reranker=None, relevance_model=None):
        from infrastructure.sqlite import connection as routing
        requested = Path(path).resolve()
        # Schema DDL must run with cognition as main, including backup imports
        # initiated through the core database path.
        self.path = (routing.COGNITION_DATABASE_PATH
                     if requested in {routing.DATABASE_PATH.resolve(), routing.CONTENT_DATABASE_PATH.resolve()}
                     else requested)
        self.fts_available = False
        self.embedding_adapter = embedding_adapter
        self.query_expander = query_expander
        self.reranker = reranker
        self.relevance_model = relevance_model
    @contextmanager
    def connect(self, write=False):
        from infrastructure.sqlite.connection import connect, write_transaction
        c = connect(self.path)
        c.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                with write_transaction(c):
                    yield c
            else:
                yield c
        except Exception:
            if c.in_transaction:
                c.rollback()
            raise
        finally:
            c.close()
    def initialize(self):
        self._migrate_segment_names()
        with self.connect() as c:
            # WAL lets the single-user app read while short background memory
            # transactions commit. It persists on the database file.
            c.execute('PRAGMA journal_mode=WAL')
            c.execute('PRAGMA synchronous=NORMAL')
            c.executescript(Path(__file__).with_name('source_schema.sql').read_text(encoding='utf-8'))
            try:
                c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS lmc_fts USING fts5(memory_id UNINDEXED, search_text)")
                self.fts_available = True
            except sqlite3.OperationalError:
                self.fts_available = False
            c.execute("INSERT OR IGNORE INTO memory_config VALUES ('initialized_at',?)", (utc(),))
            c.execute("INSERT OR IGNORE INTO memory_config VALUES ('schema_version','2')")
            c.commit()
        self._migrate_source_queue()
        from .lmc import initialize as initialize_lmc
        initialize_lmc(self)
        from .calendar import initialize as initialize_calendar
        initialize_calendar(self)
        from .dream import initialize as initialize_dream
        initialize_dream(self)
        with self.connect() as c:
            needs_rebuild = bool(c.execute('''SELECT 1 FROM lmc_memories m
                LEFT JOIN lmc_search_documents d USING(memory_id)
                WHERE d.memory_id IS NULL OR d.revision!=m.revision OR d.tokenizer_version!=? LIMIT 1''',
                (TOKENIZER_VERSION,)).fetchone())
            if self.fts_available:
                needs_rebuild |= c.execute('SELECT COUNT(*) FROM lmc_fts').fetchone()[0] != c.execute('SELECT COUNT(*) FROM lmc_search_documents').fetchone()[0]
        if needs_rebuild:
            self.rebuild_index()
    def _migrate_segment_names(self):
        """在创建新表之前迁移旧表和字段，保留原有编号及外键关联。"""
        with self.connect(True) as c:
            schema = c.route_schemas.get('cognition', 'main')
            tables = {r[0] for r in c.execute(f'SELECT name FROM {schema}.sqlite_master WHERE type=?', ('table',))}
            if 'conversation_segments' in tables:
                if 'experience_segments' in tables:
                    raise ValidationError('ambiguous_segment_tables')
                c.execute(f'ALTER TABLE {schema}.conversation_segments RENAME TO experience_segments')
            elif 'experience_segments' not in tables:
                return
            columns = {r['name'] for r in c.execute(f'PRAGMA {schema}.table_info(experience_segments)')}
            for old, new in [('focus', 'preview'), ('last_activity_at', 'ended_at'), ('close_reason', 'boundary_reason')]:
                if old in columns:
                    c.execute(f'ALTER TABLE {schema}.experience_segments RENAME COLUMN {old} TO {new}')
            if 'thread_id' in columns:
                c.execute(f'DROP INDEX IF EXISTS {schema}.idx_segment_open')
                c.execute(f'ALTER TABLE {schema}.experience_segments DROP COLUMN thread_id')
            # 预览和发生时间直接由关联原文提供，不在片段表重复保存。
            columns = {r['name'] for r in c.execute(f'PRAGMA {schema}.table_info(experience_segments)')}
            for column in ('preview', 'started_at', 'ended_at'):
                if column in columns:
                    c.execute(f'ALTER TABLE {schema}.experience_segments DROP COLUMN {column}')


    def _migrate_source_queue(self):
        """Preserve source/segment migrations and retire obsolete queue jobs."""
        with self.connect(True) as c:
            # 消息流归属直接保存在片段上；迁移旧映射后移除多余的表。
            segment_columns = {row['name'] for row in c.execute('PRAGMA table_info(experience_segments)')}
            if 'stream_key' not in segment_columns:
                c.execute('ALTER TABLE experience_segments ADD COLUMN stream_key TEXT')
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='segment_streams'").fetchone():
                c.execute('''UPDATE experience_segments SET stream_key=(
                    SELECT stream_key FROM segment_streams g
                    WHERE g.segment_id=experience_segments.segment_id)
                    WHERE stream_key IS NULL AND segment_id IN (SELECT segment_id FROM segment_streams)''')
                c.execute("UPDATE experience_segments SET stream_key=NULL WHERE stream_key LIKE 'event:%'")
                c.execute('DROP TABLE segment_streams')
            c.execute('CREATE INDEX IF NOT EXISTS idx_segment_stream ON experience_segments(stream_key,segment_state)')
            # 将旧的逐条候选标记转换为每条消息流的处理位置，再移除旧字段。
            raw_columns = {row['name'] for row in c.execute('PRAGMA table_info(raw_experiences)')}
            if 'candidate_stream' in raw_columns:
                for row in c.execute('SELECT candidate_stream,MAX(rowid) AS position FROM raw_experiences WHERE candidate_stream IS NOT NULL GROUP BY candidate_stream').fetchall():
                    self._advance_progress(c, row['candidate_stream'], max(row['position'], self._stream_progress(c, row['candidate_stream'])))
                c.execute('DROP INDEX IF EXISTS idx_raw_candidates')
                c.execute('ALTER TABLE raw_experiences DROP COLUMN candidate_stream')
            # 旧的未结束片段恢复为尚未成段的原文，已完成片段保持不变。
            for segment in c.execute("SELECT segment_id,stream_key FROM experience_segments WHERE segment_state='open' AND stream_key IS NOT NULL AND NOT EXISTS (SELECT 1 FROM memory_jobs j WHERE j.segment_id=experience_segments.segment_id)").fetchall():
                position = c.execute('SELECT MAX(r.rowid) FROM raw_experiences r JOIN segment_experiences e USING(experience_id) WHERE e.segment_id=?', (segment['segment_id'],)).fetchone()[0]
                c.execute('UPDATE raw_experiences SET segmented=0 WHERE experience_id IN (SELECT experience_id FROM segment_experiences WHERE segment_id=?)', (segment['segment_id'],))
                if position is not None:
                    self._advance_progress(c, segment['stream_key'], max(position, self._stream_progress(c, segment['stream_key'])))
                c.execute('DELETE FROM segment_experiences WHERE segment_id=?', (segment['segment_id'],))
                c.execute('DELETE FROM experience_segments WHERE segment_id=?', (segment['segment_id'],))
            c.execute("DELETE FROM memory_config WHERE key='candidate_buffer_migrated'")
            c.execute("UPDATE raw_experiences SET actor='libra' WHERE actor='assistant'")
            columns = {row['name'] for row in c.execute('PRAGMA table_info(memory_jobs)')}
            for name, declaration in {'job_kind': "TEXT NOT NULL DEFAULT 'lmc'",
                                      'input_json': "TEXT NOT NULL DEFAULT '{}'", 'dedupe_key': 'TEXT'}.items():
                if name not in columns:
                    c.execute(f'ALTER TABLE memory_jobs ADD COLUMN {name} {declaration}')
            c.execute("UPDATE memory_jobs SET job_kind='lmc' WHERE job_kind='episode'")
            c.execute("UPDATE memory_jobs SET job_status='failed',error_code='feature_removed',lease_token=NULL,lease_until=NULL WHERE job_kind!='lmc' AND job_status IN ('pending','processing','retryable')")
            c.execute("INSERT INTO memory_config VALUES ('schema_version','3') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    def rebuild_index(self):
        with self.connect(True) as c:
            if self.fts_available:
                c.execute('DELETE FROM lmc_fts')
            for row in c.execute('''SELECT m.memory_id,m.revision,m.title,m.content,COALESCE(e.topics_json,'[]') AS topics_json
                FROM lmc_memories m LEFT JOIN lmc_event_context e USING(memory_id)''').fetchall():
                self._index(c,row['memory_id'],row['revision'],row['title']+' '+row['content']+' '+' '.join(json.loads(row['topics_json'])))
    def _embed(self, text):
        adapter=self.embedding_adapter
        vector=adapter.embed(text,timeout_seconds=2.0)
        if len(vector)!=adapter.dimensions or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in vector):
            raise ValidationError('invalid_embedding')
        norm=math.sqrt(sum(v*v for v in vector))
        if not norm:
            raise ValidationError('zero_embedding')
        return [v/norm for v in vector]
    def refresh_embeddings(self, limit=10):
        """Rebuild stale vectors outside write transactions; recheck revision on commit."""
        adapter=self.embedding_adapter
        if adapter is None:
            return 0
        with self.connect() as c:
            rows=c.execute('''SELECT m.memory_id,m.revision,m.title,m.content FROM lmc_memories m
                LEFT JOIN lmc_embeddings e USING(memory_id) WHERE m.record_status='active' AND m.memory_kind='lmc'
                AND (e.memory_id IS NULL OR e.revision!=m.revision OR e.model_id!=? OR e.dimensions!=? OR e.tokenizer_version!=?)
                LIMIT ?''',(adapter.model_id,adapter.dimensions,TOKENIZER_VERSION,max(1,min(limit,100)))).fetchall()
        count=0
        for row in rows:
            vector=self._embed(row['title']+'\n'+row['content'])
            with self.connect(True) as c:
                current=c.execute("SELECT revision FROM lmc_memories WHERE memory_id=? AND record_status='active'",(row['memory_id'],)).fetchone()
                if current and current[0]==row['revision']:
                    c.execute('''INSERT INTO lmc_embeddings VALUES (?,?,?,?,?,?) ON CONFLICT(memory_id) DO UPDATE SET
                        revision=excluded.revision,model_id=excluded.model_id,dimensions=excluded.dimensions,
                        tokenizer_version=excluded.tokenizer_version,vector_json=excluded.vector_json''',
                        (row['memory_id'],row['revision'],adapter.model_id,adapter.dimensions,TOKENIZER_VERSION,dumps(vector)))
                    count+=1
        return count
    def _index(self, c, memory_id, revision, content):
        search_text = ' '.join(sorted(tokens(content)))
        c.execute('''INSERT INTO lmc_search_documents VALUES (?,?,?,?) ON CONFLICT(memory_id)
            DO UPDATE SET revision=excluded.revision,search_text=excluded.search_text,tokenizer_version=excluded.tokenizer_version''',
            (memory_id,revision,search_text,TOKENIZER_VERSION))
        if self.fts_available:
            c.execute('DELETE FROM lmc_fts WHERE memory_id=?', (memory_id,))
            c.execute('INSERT INTO lmc_fts VALUES (?,?)', (memory_id,search_text))
