-- Source journal and segment extraction queue; no legacy memory storage.
CREATE TABLE IF NOT EXISTS memory_config (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_experiences (
    experience_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL CHECK(source_type IN ('chat_message','unified_event','state_snapshot')),
    source_system TEXT NOT NULL, source_id TEXT NOT NULL,
    thread_id TEXT, session_id TEXT, actor TEXT NOT NULL,
    content TEXT NOT NULL, occurred_at TEXT NOT NULL, ingested_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    source_status TEXT NOT NULL DEFAULT 'active' CHECK(source_status IN ('active','invalid')),
    segmented INTEGER NOT NULL DEFAULT 0 CHECK(segmented IN (0,1)),
    UNIQUE(source_system, source_id)
);
CREATE INDEX IF NOT EXISTS idx_raw_pending ON raw_experiences(segmented, ingested_at);
CREATE INDEX IF NOT EXISTS idx_raw_active_time ON raw_experiences(source_status, occurred_at DESC);
CREATE TABLE IF NOT EXISTS experience_segments (
    segment_id TEXT PRIMARY KEY,
    segment_state TEXT NOT NULL CHECK(segment_state IN ('open','closed','processed','discarded')),
    boundary_reason TEXT, stream_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_segment_state ON experience_segments(segment_state);
CREATE TABLE IF NOT EXISTS memory_stream_boundaries (
    stream_key TEXT NOT NULL, cutoff INTEGER NOT NULL, reason TEXT NOT NULL,
    created_at TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(stream_key, cutoff)
);
CREATE TABLE IF NOT EXISTS segment_experiences (
    segment_id TEXT NOT NULL REFERENCES experience_segments(segment_id),
    experience_id TEXT NOT NULL REFERENCES raw_experiences(experience_id),
    PRIMARY KEY(segment_id, experience_id)
);
CREATE TABLE IF NOT EXISTS memory_jobs (
    job_id TEXT PRIMARY KEY, segment_id TEXT UNIQUE REFERENCES experience_segments(segment_id),
    decision_id TEXT NOT NULL UNIQUE, job_status TEXT NOT NULL
      CHECK(job_status IN ('pending','processing','committed','retryable','failed')),
    attempts INTEGER NOT NULL DEFAULT 0, lease_token TEXT, lease_until TEXT,
    next_attempt_at TEXT NOT NULL, error_code TEXT,
    result_json TEXT, job_kind TEXT NOT NULL DEFAULT 'lmc',
    input_json TEXT NOT NULL DEFAULT '{}', dedupe_key TEXT UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_jobs_ready ON memory_jobs(job_status, next_attempt_at);

CREATE TABLE IF NOT EXISTS cognitive_traces (
 request_id TEXT PRIMARY KEY, trace_json TEXT NOT NULL, created_at TEXT NOT NULL
);
