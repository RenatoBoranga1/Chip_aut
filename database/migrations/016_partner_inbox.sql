CREATE TABLE partner_inbox (
 id INTEGER PRIMARY KEY, partner TEXT NOT NULL, filename TEXT NOT NULL,
 file_hash TEXT NOT NULL, detected_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('DETECTED','VALIDATING','READY_FOR_REVIEW','INVALID','DUPLICATE','IMPORTED','REJECTED')),
 revision INTEGER NOT NULL DEFAULT 1, stat_json TEXT NOT NULL,
 mode TEXT NOT NULL DEFAULT 'INCREMENTAL' CHECK(mode IN ('INCREMENTAL','FULL_SNAPSHOT')),
 mapping_json TEXT NOT NULL DEFAULT '{}', preview_json TEXT NOT NULL DEFAULT '{}',
 preview_hash TEXT, error TEXT, import_id INTEGER REFERENCES partner_inventory_imports(id),
 UNIQUE(partner,filename,file_hash)
);
CREATE INDEX partner_inbox_by_hash ON partner_inbox(partner,file_hash);
CREATE INDEX partner_inbox_by_name ON partner_inbox(partner,filename,id DESC);
CREATE TABLE partner_inbox_scans (
 partner TEXT PRIMARY KEY, last_scan_at TEXT NOT NULL, result_json TEXT NOT NULL
);
CREATE TABLE partner_health_state (
 partner TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE partner_inbox_errors (
 partner TEXT NOT NULL, filename TEXT NOT NULL, stat_json TEXT NOT NULL,
 error TEXT NOT NULL, updated_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(partner,filename)
);
