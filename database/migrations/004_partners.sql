CREATE TABLE IF NOT EXISTS partner_collections (
    id INTEGER PRIMARY KEY,
    partner TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('COMPLETE','PARTIAL','FAILED','CACHED')),
    summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS partner_advertisements (
    partner TEXT NOT NULL,
    external_id TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    verification_count INTEGER NOT NULL,
    not_seen_in_latest_collection INTEGER NOT NULL CHECK(not_seen_in_latest_collection IN (0,1)),
    latest_collection_id INTEGER NOT NULL REFERENCES partner_collections(id),
    payload_json TEXT NOT NULL,
    PRIMARY KEY(partner,external_id)
);
CREATE TABLE IF NOT EXISTS partner_observations (
    collection_id INTEGER NOT NULL REFERENCES partner_collections(id),
    partner TEXT NOT NULL,
    external_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(collection_id,partner,external_id),
    FOREIGN KEY(partner,external_id) REFERENCES partner_advertisements(partner,external_id)
);
