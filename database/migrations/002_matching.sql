CREATE TABLE IF NOT EXISTS matching_runs (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    policy_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    requires_review INTEGER NOT NULL CHECK(requires_review IN (0,1))
);
CREATE TABLE IF NOT EXISTS matching_reviews (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES matching_runs(id),
    created_at TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('CONFIRMAR','SEM_CORRESPONDENCIA')),
    scanner_key TEXT REFERENCES motorcycles(normalized_key),
    note TEXT NOT NULL,
    CHECK((decision = 'CONFIRMAR' AND scanner_key IS NOT NULL) OR
          (decision = 'SEM_CORRESPONDENCIA' AND scanner_key IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_reviews_run ON matching_reviews(run_id, id);
CREATE INDEX IF NOT EXISTS idx_runs_pending ON matching_runs(requires_review, id);
