CREATE TABLE alert_deliveries (
    pipeline_run_id INTEGER PRIMARY KEY REFERENCES pipeline_runs(id),
    context_json TEXT NOT NULL,
    processed_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT
);
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY,
    deduplication_key TEXT NOT NULL UNIQUE,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('INFO','ATENCAO','ALTA','CRITICA')),
    status TEXT NOT NULL DEFAULT 'NOVO' CHECK(status IN ('NOVO','LIDO','ARQUIVADO','RESOLVIDO')),
    partner TEXT NOT NULL,
    external_id TEXT,
    manufacturer TEXT,
    scanner_key TEXT,
    review_item_id INTEGER REFERENCES review_items(id),
    pipeline_run_id INTEGER NOT NULL REFERENCES pipeline_runs(id),
    collection_run_id INTEGER REFERENCES partner_collections(id),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    condition_active INTEGER NOT NULL DEFAULT 1,
    read_at TEXT,
    archived_at TEXT,
    resolved_at TEXT
);
CREATE INDEX alerts_filters ON alerts(partner,status,severity,alert_type);
CREATE TABLE alert_occurrences (
    id INTEGER PRIMARY KEY,
    alert_id INTEGER NOT NULL REFERENCES alerts(id),
    event_key TEXT NOT NULL,
    pipeline_run_id INTEGER NOT NULL REFERENCES pipeline_runs(id),
    created_at TEXT NOT NULL,
    details_json TEXT NOT NULL,
    UNIQUE(alert_id,event_key)
);
CREATE TABLE alert_history (
    id INTEGER PRIMARY KEY,
    alert_id INTEGER NOT NULL REFERENCES alerts(id),
    created_at TEXT NOT NULL,
    action TEXT NOT NULL,
    before_status TEXT,
    after_status TEXT NOT NULL
);
CREATE TRIGGER alert_history_no_update BEFORE UPDATE ON alert_history
BEGIN SELECT RAISE(ABORT,'Alert history is append-only'); END;
CREATE TRIGGER alert_history_no_delete BEFORE DELETE ON alert_history
BEGIN SELECT RAISE(ABORT,'Alert history is append-only'); END;
