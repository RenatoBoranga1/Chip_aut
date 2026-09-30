CREATE TABLE scanner_versions (
 id INTEGER PRIMARY KEY, original_filename TEXT NOT NULL, sha256 TEXT NOT NULL,
 imported_at TEXT NOT NULL, published_at TEXT, imported_by TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('VALIDATED','REJECTED','PUBLISHED','SUPERSEDED')),
 total_records INTEGER NOT NULL DEFAULT 0, valid_records INTEGER NOT NULL DEFAULT 0,
 unique_vehicles INTEGER NOT NULL DEFAULT 0, invalid_records INTEGER NOT NULL DEFAULT 0,
 notes TEXT NOT NULL DEFAULT '', parent_import_id INTEGER REFERENCES imports(id),
 import_id INTEGER UNIQUE REFERENCES imports(id), content BLOB,
 payload_json TEXT, policy_json TEXT, report_json TEXT NOT NULL DEFAULT '{}', impact_token TEXT
);
CREATE UNIQUE INDEX scanner_one_published ON scanner_versions(status) WHERE status='PUBLISHED';
CREATE INDEX scanner_hash ON scanner_versions(sha256);
INSERT INTO scanner_versions(original_filename,sha256,imported_at,published_at,imported_by,status,import_id,unique_vehicles)
 SELECT source_path,source_sha256,created_at,created_at,'Importação anterior',
 CASE WHEN id=(SELECT MAX(id) FROM imports) THEN 'PUBLISHED' ELSE 'SUPERSEDED' END,id,
 (SELECT COUNT(*) FROM motorcycle_snapshots WHERE import_id=imports.id) FROM imports ORDER BY id;
CREATE TABLE scanner_differences (
 id INTEGER PRIMARY KEY,version_id INTEGER NOT NULL REFERENCES scanner_versions(id),kind TEXT NOT NULL,
 identity_key TEXT NOT NULL,payload_json TEXT NOT NULL
);
CREATE INDEX scanner_diff_page ON scanner_differences(version_id,kind,id);
CREATE TABLE scanner_impacts (
 id INTEGER PRIMARY KEY,version_id INTEGER NOT NULL REFERENCES scanner_versions(id),kind TEXT NOT NULL,
 entity_id INTEGER NOT NULL,payload_json TEXT NOT NULL
);
CREATE INDEX scanner_impact_page ON scanner_impacts(version_id,kind,id);
CREATE TABLE scanner_events (
 id INTEGER PRIMARY KEY,version_id INTEGER NOT NULL REFERENCES scanner_versions(id),created_at TEXT NOT NULL,
 actor TEXT NOT NULL,action TEXT NOT NULL,notes TEXT NOT NULL,payload_json TEXT NOT NULL
);
CREATE TRIGGER scanner_events_no_update BEFORE UPDATE ON scanner_events BEGIN SELECT RAISE(ABORT,'Histórico imutável'); END;
CREATE TRIGGER scanner_events_no_delete BEFORE DELETE ON scanner_events BEGIN SELECT RAISE(ABORT,'Histórico imutável'); END;
CREATE TRIGGER scanner_published_no_delete BEFORE DELETE ON scanner_versions WHEN OLD.import_id IS NOT NULL BEGIN SELECT RAISE(ABORT,'Versão publicada preservada'); END;
CREATE TABLE scanner_jobs (
 version_id INTEGER PRIMARY KEY REFERENCES scanner_versions(id),import_id INTEGER NOT NULL REFERENCES imports(id),
 status TEXT NOT NULL DEFAULT 'PENDING',attempts INTEGER NOT NULL DEFAULT 0,message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE scanner_alerts (
 id INTEGER PRIMARY KEY,version_id INTEGER NOT NULL REFERENCES scanner_versions(id),partner TEXT NOT NULL,
 event_key TEXT NOT NULL UNIQUE,alert_type TEXT NOT NULL,title TEXT NOT NULL,message TEXT NOT NULL,
 created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'NOVO'
);
CREATE TABLE scanner_alert_history (
 id INTEGER PRIMARY KEY,alert_id INTEGER NOT NULL REFERENCES scanner_alerts(id),created_at TEXT NOT NULL,
 action TEXT NOT NULL,before_status TEXT,after_status TEXT NOT NULL
);
CREATE TRIGGER scanner_alert_history_no_update BEFORE UPDATE ON scanner_alert_history BEGIN SELECT RAISE(ABORT,'Histórico imutável'); END;
CREATE TRIGGER scanner_alert_history_no_delete BEFORE DELETE ON scanner_alert_history BEGIN SELECT RAISE(ABORT,'Histórico imutável'); END;
