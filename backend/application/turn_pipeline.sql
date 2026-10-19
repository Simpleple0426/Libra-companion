CREATE TABLE IF NOT EXISTS cognition_turns (
 turn_id TEXT PRIMARY KEY, source_key TEXT NOT NULL UNIQUE, source TEXT NOT NULL,
 status TEXT NOT NULL, context_json TEXT NOT NULL, plan_json TEXT NOT NULL,
 response_json TEXT, verdict_json TEXT, created_at TEXT NOT NULL, committed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_cognition_turns_created
 ON cognition_turns(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cognition_turns_status_created
 ON cognition_turns(status, created_at DESC);
CREATE TABLE IF NOT EXISTS cognition_context_revisions (
 turn_id TEXT NOT NULL REFERENCES cognition_turns(turn_id), revision INTEGER NOT NULL,
 snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(turn_id,revision)
);
CREATE TABLE IF NOT EXISTS cognition_delivery (
 turn_id TEXT PRIMARY KEY REFERENCES cognition_turns(turn_id), status TEXT NOT NULL,
 message_ids_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cognition_post_jobs (
 turn_id TEXT PRIMARY KEY REFERENCES cognition_turns(turn_id), status TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, error_code TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cognition_feedback (
 feedback_id TEXT PRIMARY KEY, turn_id TEXT NOT NULL REFERENCES cognition_turns(turn_id),
 kind TEXT NOT NULL, evidence_ref TEXT, value_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cognition_actions (
 turn_id TEXT PRIMARY KEY REFERENCES cognition_turns(turn_id),
 plan_json TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cognition_inputs (
 request_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
 message_id INTEGER NOT NULL REFERENCES messages(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cognition_notifications (
 turn_id TEXT PRIMARY KEY REFERENCES cognition_turns(turn_id),
 message_ids_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cognition_call_inputs (
 request_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
 call_turn_id INTEGER NOT NULL REFERENCES call_turns(id), created_at TEXT NOT NULL
);
