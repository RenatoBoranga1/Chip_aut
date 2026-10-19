CREATE TABLE partner_inventory_imports (
 id INTEGER PRIMARY KEY, partner TEXT NOT NULL, created_at TEXT NOT NULL,
 filename TEXT NOT NULL, file_hash TEXT NOT NULL, batch_key TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('INCREMENTAL','FULL_SNAPSHOT')),
 total_rows INTEGER NOT NULL, valid_rows INTEGER NOT NULL, invalid_rows INTEGER NOT NULL,
 imported_rows INTEGER NOT NULL, duplicates INTEGER NOT NULL, user_action TEXT NOT NULL,
 reviewer TEXT NOT NULL, status TEXT NOT NULL, collection_id INTEGER REFERENCES partner_collections(id),
 UNIQUE(partner,batch_key)
);
CREATE TABLE partner_import_mappings (
 partner TEXT PRIMARY KEY, mapping_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE partner_staging (
 partner TEXT NOT NULL, external_id TEXT NOT NULL, signature TEXT NOT NULL,
 payload_json TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
 classification TEXT NOT NULL CHECK(classification IN ('PENDING_CLASSIFICATION','MOTORCYCLE','KART','SERVICE','OTHER','UNKNOWN')),
 revision INTEGER NOT NULL DEFAULT 1, identity_json TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(partner,external_id)
);
CREATE TABLE partner_operation_events (
 id INTEGER PRIMARY KEY, partner TEXT NOT NULL, external_id TEXT, created_at TEXT NOT NULL,
 action TEXT NOT NULL, reviewer TEXT NOT NULL, detail_json TEXT NOT NULL
);
CREATE TRIGGER partner_operation_events_no_update BEFORE UPDATE ON partner_operation_events
BEGIN SELECT RAISE(ABORT,'Operational events are append-only'); END;
CREATE TRIGGER partner_operation_events_no_delete BEFORE DELETE ON partner_operation_events
BEGIN SELECT RAISE(ABORT,'Operational events are append-only'); END;
CREATE TABLE partner_operation_alerts (
 partner TEXT NOT NULL, code TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, occurrences INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(partner,code)
);
