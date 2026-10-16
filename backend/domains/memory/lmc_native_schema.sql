-- Native LMC storage; legacy tables are migration inputs only.
CREATE TABLE IF NOT EXISTS lmc_candidates (
    candidate_id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
    segment_id TEXT NOT NULL, candidate_index INTEGER NOT NULL,
    title TEXT NOT NULL, content TEXT NOT NULL, primary_scope TEXT NOT NULL,
    importance INTEGER NOT NULL, confidence REAL NOT NULL, sensitivity TEXT NOT NULL,
    proposal_json TEXT NOT NULL, source_ids_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL, created_at TEXT NOT NULL,
    decision TEXT NOT NULL, reason TEXT NOT NULL, memory_id TEXT,
    UNIQUE(job_id, candidate_index)
);

CREATE TABLE IF NOT EXISTS lmc_memories (
    memory_id TEXT PRIMARY KEY,
    primary_scope TEXT NOT NULL CHECK(primary_scope IN ('user','self','shared')),
    memory_kind TEXT NOT NULL DEFAULT 'lmc' CHECK(memory_kind='lmc'),
    memory_subtype TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
    record_status TEXT NOT NULL DEFAULT 'active' CHECK(record_status IN ('active','superseded','invalid')),
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    importance REAL NOT NULL CHECK(importance BETWEEN 0 AND 1),
    sensitivity TEXT NOT NULL CHECK(sensitivity IN ('normal','sensitive','highly_sensitive')),
    retention_class TEXT NOT NULL DEFAULT 'long_term' CHECK(retention_class IN ('long_term','protected')),
    protected INTEGER NOT NULL DEFAULT 0 CHECK(protected IN (0,1)),
    protection_reason TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1, revision INTEGER NOT NULL CHECK(revision > 0),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lmc_event_context (
    memory_id TEXT PRIMARY KEY REFERENCES lmc_memories(memory_id),
    episode_phase TEXT NOT NULL CHECK(episode_phase IN ('candidate','ongoing','finalized')),
    occurred_start TEXT NOT NULL, occurred_end TEXT,
    time_precision TEXT NOT NULL DEFAULT 'reported',
    participants_json TEXT NOT NULL, topics_json TEXT NOT NULL,
    affect_json TEXT NOT NULL DEFAULT '{}', commitments_json TEXT NOT NULL DEFAULT '[]',
    inferences_json TEXT NOT NULL DEFAULT '[]', event_identity TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lmc_sources (
    memory_id TEXT NOT NULL REFERENCES lmc_memories(memory_id),
    experience_id TEXT NOT NULL REFERENCES raw_experiences(experience_id),
    relation TEXT NOT NULL CHECK(relation IN ('direct_evidence','context','update','contradiction')),
    evidence_quote TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(memory_id, experience_id, relation)
);
CREATE INDEX IF NOT EXISTS native_sources_experience ON lmc_sources(experience_id);
CREATE INDEX IF NOT EXISTS native_memory_scope_status ON lmc_memories(primary_scope,record_status);
CREATE INDEX IF NOT EXISTS native_event_time ON lmc_event_context(occurred_start);

CREATE TABLE IF NOT EXISTS lmc_revisions (
    memory_id TEXT NOT NULL REFERENCES lmc_memories(memory_id), revision INTEGER NOT NULL,
    operation TEXT NOT NULL, snapshot_json TEXT NOT NULL, explanation TEXT NOT NULL,
    created_at TEXT NOT NULL, PRIMARY KEY(memory_id, revision)
);

CREATE TABLE IF NOT EXISTS lmc_usage_events (
    event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL,
    memory_id TEXT NOT NULL REFERENCES lmc_memories(memory_id),
    usage_kind TEXT NOT NULL CHECK(usage_kind IN ('context_selected','response_used')),
    created_at TEXT NOT NULL, UNIQUE(request_id, memory_id, usage_kind)
);

CREATE TABLE IF NOT EXISTS lmc_search_documents (
    memory_id TEXT PRIMARY KEY REFERENCES lmc_memories(memory_id), revision INTEGER NOT NULL,
    search_text TEXT NOT NULL, tokenizer_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lmc_recall_logs (
    request_id TEXT PRIMARY KEY, query_intent TEXT NOT NULL, trace_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lmc_session_recall (
    session_id TEXT NOT NULL,
    memory_id TEXT NOT NULL REFERENCES lmc_memories(memory_id),
    recalled_at TEXT NOT NULL,
    PRIMARY KEY(session_id, memory_id)
);

CREATE TABLE IF NOT EXISTS lmc_embeddings (
    memory_id TEXT PRIMARY KEY REFERENCES lmc_memories(memory_id),
    revision INTEGER NOT NULL, model_id TEXT NOT NULL, dimensions INTEGER NOT NULL,
    tokenizer_version TEXT NOT NULL, vector_json TEXT NOT NULL
);

-- LMC-5 coordinates over the application's canonical memory/source records.
CREATE TABLE IF NOT EXISTS lmc_memory_coordinates (
 memory_id TEXT PRIMARY KEY REFERENCES lmc_memories(memory_id),
 category TEXT NOT NULL, thread TEXT NOT NULL DEFAULT 'other',
 fact_key TEXT, fact_value TEXT, status TEXT NOT NULL DEFAULT 'current'
 CHECK(status IN ('current','review','superseded','historical','archived')),
 active_fact INTEGER NOT NULL DEFAULT 1,
 supersedes_id TEXT REFERENCES lmc_memories(memory_id),
 content_hash TEXT NOT NULL, source_revision INTEGER NOT NULL,
 e_authored_by TEXT, e_initial_priority INTEGER,
 valence REAL, arousal REAL, response_tendency TEXT,
 vitality REAL NOT NULL DEFAULT 1, last_maintained_at TEXT,
 CHECK(e_initial_priority IS NULL OR e_initial_priority BETWEEN 1 AND 100),
 CHECK(valence IS NULL OR valence BETWEEN -1 AND 1),
 CHECK(arousal IS NULL OR arousal BETWEEN 0 AND 1)
);
CREATE INDEX IF NOT EXISTS native_idx_lmc_fact ON lmc_memory_coordinates(fact_key,status);
CREATE INDEX IF NOT EXISTS native_idx_lmc_thread ON lmc_memory_coordinates(thread,status);
CREATE TRIGGER IF NOT EXISTS native_lmc_e_immutable BEFORE UPDATE OF
 e_authored_by,e_initial_priority,valence,arousal,response_tendency ON lmc_memory_coordinates
 WHEN OLD.e_authored_by IS NOT NULL AND (
 NEW.e_authored_by IS NOT OLD.e_authored_by OR NEW.e_initial_priority IS NOT OLD.e_initial_priority
 OR NEW.valence IS NOT OLD.valence OR NEW.arousal IS NOT OLD.arousal
 OR NEW.response_tendency IS NOT OLD.response_tendency)
 BEGIN SELECT RAISE(ABORT,'primary_experience_is_immutable'); END;
CREATE UNIQUE INDEX IF NOT EXISTS native_idx_lmc_current_fact ON lmc_memory_coordinates(fact_key)
 WHERE fact_key IS NOT NULL AND status='current' AND active_fact=1;
CREATE TABLE IF NOT EXISTS lmc_memory_relations (
 source_id TEXT NOT NULL REFERENCES lmc_memories(memory_id),
 target_id TEXT NOT NULL REFERENCES lmc_memories(memory_id),
 relation_type TEXT NOT NULL, strength REAL NOT NULL CHECK(strength BETWEEN 0 AND 1),
 source_revision INTEGER NOT NULL, target_revision INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('active','review','invalid')),
 evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(source_id,target_id,relation_type), CHECK(source_id!=target_id)
);
CREATE INDEX IF NOT EXISTS native_idx_lmc_relation_target ON lmc_memory_relations(target_id,status);
CREATE TABLE IF NOT EXISTS lmc_relation_jobs (
 job_id TEXT PRIMARY KEY, memory_id TEXT NOT NULL REFERENCES lmc_memories(memory_id),
 source_revision INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, lease_token TEXT, lease_until TEXT,
 next_attempt_at TEXT NOT NULL, error_code TEXT, created_at TEXT NOT NULL,
 UNIQUE(memory_id,source_revision)
);
CREATE TABLE IF NOT EXISTS lmc_extraction_decisions (
 job_id TEXT NOT NULL, candidate_index INTEGER NOT NULL, decision TEXT NOT NULL,
 memory_id TEXT, reason TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(job_id,candidate_index)
);
CREATE TABLE IF NOT EXISTS lmc_memory_audits (
 audit_key TEXT PRIMARY KEY, kind TEXT NOT NULL, memory_id TEXT,
 detail_json TEXT NOT NULL, created_at TEXT NOT NULL
);
