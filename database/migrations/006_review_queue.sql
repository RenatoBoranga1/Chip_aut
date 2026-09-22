CREATE TABLE review_items (
    id INTEGER PRIMARY KEY,
    partner TEXT NOT NULL,
    external_id TEXT NOT NULL,
    signature TEXT NOT NULL,
    identity_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    state TEXT NOT NULL CHECK(state IN ('pending','resolved','ignored','deferred','invalidated','reused')),
    priority TEXT NOT NULL CHECK(priority IN ('high','medium','low')),
    collection_id INTEGER NOT NULL REFERENCES partner_collections(id),
    run_id INTEGER NOT NULL REFERENCES matching_runs(id),
    evaluated_import_id INTEGER NOT NULL REFERENCES imports(id),
    advertisement_json TEXT NOT NULL,
    automatic_json TEXT NOT NULL,
    effective_json TEXT NOT NULL,
    applied_decision_id INTEGER REFERENCES review_decisions(id),
    UNIQUE(partner,external_id,signature)
);
CREATE UNIQUE INDEX review_active_ad ON review_items(partner,external_id) WHERE active=1;
CREATE INDEX review_signature ON review_items(signature);
CREATE TABLE review_occurrences (
    id INTEGER PRIMARY KEY,
    review_item_id INTEGER NOT NULL REFERENCES review_items(id),
    collection_id INTEGER NOT NULL REFERENCES partner_collections(id),
    run_id INTEGER NOT NULL REFERENCES matching_runs(id),
    import_id INTEGER NOT NULL REFERENCES imports(id),
    policy_json TEXT NOT NULL,
    advertisement_json TEXT NOT NULL,
    automatic_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(review_item_id,collection_id,import_id,policy_json)
);
CREATE TABLE review_decisions (
    id INTEGER PRIMARY KEY,
    review_item_id INTEGER NOT NULL REFERENCES review_items(id),
    signature TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('CONFIRMAR_MATCH','REJEITAR_CANDIDATO','NAO_EXISTE_NA_BASE','DEIXAR_PENDENTE','IGNORAR')),
    reviewer TEXT NOT NULL CHECK(length(trim(reviewer))>0),
    note TEXT NOT NULL CHECK(length(trim(note))>0),
    created_at TEXT NOT NULL,
    candidate_key TEXT,
    target_identity_json TEXT,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    run_id INTEGER NOT NULL REFERENCES matching_runs(id),
    policy_json TEXT NOT NULL,
    identity_json TEXT NOT NULL,
    previous_decision_id INTEGER REFERENCES review_decisions(id),
    CHECK((action IN ('CONFIRMAR_MATCH','REJEITAR_CANDIDATO') AND candidate_key IS NOT NULL)
       OR (action NOT IN ('CONFIRMAR_MATCH','REJEITAR_CANDIDATO') AND candidate_key IS NULL))
);
CREATE INDEX review_memory ON review_decisions(signature,id);
CREATE TABLE review_events (
    id INTEGER PRIMARY KEY,
    review_item_id INTEGER NOT NULL REFERENCES review_items(id),
    created_at TEXT NOT NULL,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    decision_id INTEGER REFERENCES review_decisions(id),
    reason TEXT NOT NULL
);
CREATE TRIGGER review_decisions_no_update BEFORE UPDATE ON review_decisions
BEGIN SELECT RAISE(ABORT,'Review decisions are append-only'); END;
CREATE TRIGGER review_decisions_no_delete BEFORE DELETE ON review_decisions
BEGIN SELECT RAISE(ABORT,'Review decisions are append-only'); END;
