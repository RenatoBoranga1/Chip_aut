CREATE TABLE pipeline_runs (
    id INTEGER PRIMARY KEY,
    request_key TEXT UNIQUE,
    started_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    finished_at TEXT,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('manual','scheduled')),
    status TEXT NOT NULL CHECK(status IN ('RUNNING','SUCCESS','PARTIAL_SUCCESS','FAILED','SKIPPED_ALREADY_RUNNING','CANCELLED')),
    duration_seconds REAL,
    collection_run_id INTEGER REFERENCES partner_collections(id),
    config_hash TEXT NOT NULL,
    fingerprint TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    error_summary TEXT
);
CREATE INDEX pipeline_status ON pipeline_runs(status,id);
CREATE TABLE scheduler_state (
    id INTEGER PRIMARY KEY CHECK(id=1),
    heartbeat_at TEXT NOT NULL,
    next_run_at TEXT,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL
);
