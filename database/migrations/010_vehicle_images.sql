-- Visual metadata is separate from operational identity, matching and decisions.
CREATE TABLE partner_vehicle_images (
    partner TEXT NOT NULL,
    external_id TEXT NOT NULL,
    identity_signature TEXT NOT NULL,
    primary_image_url TEXT,
    image_source TEXT,
    image_last_seen_at TEXT,
    observed_at TEXT NOT NULL,
    PRIMARY KEY(partner, external_id),
    FOREIGN KEY(partner, external_id) REFERENCES partner_advertisements(partner, external_id)
);
CREATE TABLE partner_vehicle_image_history (
    id INTEGER PRIMARY KEY,
    partner TEXT NOT NULL,
    external_id TEXT NOT NULL,
    identity_signature TEXT NOT NULL,
    primary_image_url TEXT,
    image_source TEXT,
    observed_at TEXT NOT NULL,
    FOREIGN KEY(partner, external_id) REFERENCES partner_advertisements(partner, external_id)
);
