
CREATE TABLE IF NOT EXISTS life_observations (
    id TEXT PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS life_memories (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('event','thought')),
    description TEXT NOT NULL, created_at TEXT NOT NULL, last_accessed TEXT NOT NULL,
    importance REAL NOT NULL, keywords TEXT NOT NULL,
    evidence TEXT NOT NULL, actor_id TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS life_model_calls (
    id TEXT PRIMARY KEY, stage TEXT NOT NULL, request TEXT NOT NULL, provider TEXT NOT NULL,
    kind TEXT NOT NULL, status TEXT NOT NULL, response TEXT, metadata TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS life_cognition_runs (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, context TEXT NOT NULL, status TEXT NOT NULL, receipt TEXT
)