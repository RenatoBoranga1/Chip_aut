CREATE TABLE development_items (
    id INTEGER PRIMARY KEY,
    identity_key TEXT NOT NULL,
    identity_json TEXT NOT NULL,
    manufacturer TEXT NOT NULL,
    model TEXT NOT NULL,
    version TEXT,
    year INTEGER NOT NULL,
    scanner_key TEXT,
    base_version INTEGER NOT NULL REFERENCES imports(id),
    source_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'NEW' CHECK(status IN ('NEW','UNDER_ANALYSIS','WAITING_INFORMATION','DATA_COLLECTED','IN_DEVELOPMENT','IN_VALIDATION','COMPLETED','DISCARDED')),
    priority TEXT NOT NULL CHECK(priority IN ('high','medium','low')),
    assigned_to TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status_since TEXT NOT NULL,
    first_seen_at TEXT,
    last_seen_at TEXT,
    primary_image_url TEXT,
    checklist_json TEXT NOT NULL,
    technical_json TEXT NOT NULL DEFAULT '{}',
    completed_at TEXT,
    discarded_at TEXT,
    completion_version TEXT,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX development_active_identity ON development_items(identity_key) WHERE status NOT IN ('COMPLETED','DISCARDED');
CREATE INDEX development_filters ON development_items(status,priority,updated_at);
CREATE TABLE development_origins (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES development_items(id),
    origin_key TEXT NOT NULL,
    partner TEXT NOT NULL,
    external_id TEXT,
    review_item_id INTEGER REFERENCES review_items(id),
    alert_id INTEGER REFERENCES alerts(id),
    first_seen_at TEXT,
    last_seen_at TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT NOT NULL,
    UNIQUE(item_id,origin_key)
);
CREATE INDEX development_origins_partner ON development_origins(partner,item_id);
CREATE TABLE development_occurrences (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES development_items(id),
    observation_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(item_id,observation_key)
);
CREATE TABLE development_events (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES development_items(id),
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    justification TEXT NOT NULL
);
CREATE INDEX development_events_item ON development_events(item_id,id);
CREATE TABLE development_commands (
    command_key TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    item_id INTEGER NOT NULL REFERENCES development_items(id)
);
CREATE TABLE development_alerts (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES development_items(id),
    event_key TEXT NOT NULL UNIQUE,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('INFO','ATENCAO','ALTA')),
    status TEXT NOT NULL DEFAULT 'NOVO' CHECK(status IN ('NOVO','LIDO','ARQUIVADO','RESOLVIDO')),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE development_alert_history (
    id INTEGER PRIMARY KEY,
    alert_id INTEGER NOT NULL REFERENCES development_alerts(id),
    created_at TEXT NOT NULL,
    action TEXT NOT NULL,
    before_status TEXT,
    after_status TEXT NOT NULL
);
CREATE TABLE development_maintenance (id INTEGER PRIMARY KEY CHECK(id=1), checked_at TEXT NOT NULL);
CREATE TRIGGER development_events_no_update BEFORE UPDATE ON development_events BEGIN SELECT RAISE(ABORT,'Development history is append-only'); END;
CREATE TRIGGER development_events_no_delete BEFORE DELETE ON development_events BEGIN SELECT RAISE(ABORT,'Development history is append-only'); END;
CREATE TRIGGER development_occurrences_no_update BEFORE UPDATE ON development_occurrences BEGIN SELECT RAISE(ABORT,'Development occurrences are append-only'); END;
CREATE TRIGGER development_occurrences_no_delete BEFORE DELETE ON development_occurrences BEGIN SELECT RAISE(ABORT,'Development occurrences are append-only'); END;
CREATE TRIGGER development_alert_history_no_update BEFORE UPDATE ON development_alert_history BEGIN SELECT RAISE(ABORT,'Development alert history is append-only'); END;
CREATE TRIGGER development_alert_history_no_delete BEFORE DELETE ON development_alert_history BEGIN SELECT RAISE(ABORT,'Development alert history is append-only'); END;
