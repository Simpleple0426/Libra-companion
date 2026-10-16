CREATE TABLE IF NOT EXISTS affect_events (
 event_id TEXT PRIMARY KEY, source_key TEXT NOT NULL, event_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','committed','failed')),
 attempts INTEGER NOT NULL DEFAULT 0, lease_token TEXT, lease_until TEXT,
 context_json TEXT, appraisal_json TEXT, need_update_json TEXT, result_json TEXT,
 error_code TEXT, error_detail TEXT, failed_output TEXT,
 created_at TEXT NOT NULL, processed_at TEXT
);
CREATE INDEX IF NOT EXISTS affect_events_status ON affect_events(status,created_at);
CREATE INDEX IF NOT EXISTS affect_event_interactions ON affect_events(json_extract(event_json,'$.event_type'),json_extract(event_json,'$.occurred_at'));
CREATE TABLE IF NOT EXISTS affect_state (
 id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS affect_observations (
 observation_id TEXT PRIMARY KEY, field_path TEXT NOT NULL, value_json TEXT NOT NULL,
 observed_at TEXT NOT NULL, valid_until TEXT, source_type TEXT NOT NULL,
 source_ref TEXT NOT NULL, confidence REAL NOT NULL
);
