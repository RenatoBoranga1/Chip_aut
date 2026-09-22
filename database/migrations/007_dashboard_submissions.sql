CREATE TABLE review_submissions (
    request_id TEXT PRIMARY KEY,
    request_json TEXT NOT NULL,
    decision_id INTEGER NOT NULL REFERENCES review_decisions(id)
);
CREATE TABLE review_decision_transitions (
    decision_id INTEGER PRIMARY KEY REFERENCES review_decisions(id),
    before_state TEXT NOT NULL,
    after_state TEXT NOT NULL
);
CREATE INDEX dashboard_partner_collection ON partner_collections(partner,id);
CREATE INDEX dashboard_coverage_collection ON coverage_runs(collection_id,id);
