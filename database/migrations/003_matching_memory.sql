CREATE TABLE IF NOT EXISTS matching_memory (
    id INTEGER PRIMARY KEY,
    query_key TEXT NOT NULL,
    scanner_key TEXT NOT NULL REFERENCES motorcycles(normalized_key),
    decision TEXT NOT NULL CHECK(decision IN ('CONFIRMAR','REJEITAR','REVOGAR')),
    source_run_id INTEGER NOT NULL REFERENCES matching_runs(id),
    reviewer TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_query ON matching_memory(query_key,id);
