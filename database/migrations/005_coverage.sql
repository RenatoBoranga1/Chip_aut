-- Existing collection history remains the authoritative run store.
CREATE VIEW collection_runs AS SELECT * FROM partner_collections;
CREATE TABLE coverage_runs (
    id INTEGER PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES partner_collections(id),
    import_id INTEGER NOT NULL REFERENCES imports(id),
    created_at TEXT NOT NULL,
    report_json TEXT NOT NULL
);
