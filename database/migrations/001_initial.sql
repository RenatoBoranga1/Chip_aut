CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES (1);
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    report_json TEXT NOT NULL,
    diff_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS motorcycles (
    id INTEGER PRIMARY KEY,
    normalized_key TEXT NOT NULL UNIQUE,
    first_import_id INTEGER NOT NULL REFERENCES imports(id)
);
CREATE TABLE IF NOT EXISTS motorcycle_snapshots (
    import_id INTEGER NOT NULL REFERENCES imports(id),
    motorcycle_id INTEGER NOT NULL REFERENCES motorcycles(id),
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (import_id, motorcycle_id)
);
CREATE TABLE IF NOT EXISTS system_records (
    id INTEGER PRIMARY KEY,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    motorcycle_id INTEGER NOT NULL REFERENCES motorcycles(id),
    sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(import_id, sheet, source_row)
);
CREATE TABLE IF NOT EXISTS import_issues (
    id INTEGER PRIMARY KEY,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    code TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_system_import ON system_records(import_id, motorcycle_id);
