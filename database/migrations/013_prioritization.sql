CREATE TABLE priority_cases (
 id INTEGER PRIMARY KEY, partner TEXT NOT NULL, entity_type TEXT NOT NULL DEFAULT 'advertisement',
 entity_id TEXT NOT NULL, identity_key TEXT NOT NULL, latest_assessment_id INTEGER REFERENCES priority_assessments(id),
 manual_priority TEXT CHECK(manual_priority IN ('high','medium','low')),
 override_reason TEXT, override_author TEXT, override_at TEXT,
 revision INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1,
 UNIQUE(partner,entity_type,entity_id,identity_key)
);
CREATE TABLE priority_assessments (
 id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES priority_cases(id),
 calculated_at TEXT NOT NULL, material_hash TEXT NOT NULL, origin TEXT NOT NULL,
 score REAL CHECK(score IS NULL OR score BETWEEN 0 AND 100), suggested_priority TEXT NOT NULL,
 confidence TEXT NOT NULL, policy_hash TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX priority_assessment_case ON priority_assessments(case_id,id);
CREATE TABLE priority_overrides (
 id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES priority_cases(id),
 created_at TEXT NOT NULL, author TEXT NOT NULL, reason TEXT NOT NULL,
 before_priority TEXT, after_priority TEXT, request_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL
);
CREATE TABLE priority_maintenance (
 partner TEXT PRIMARY KEY, checked_at TEXT NOT NULL, source_token TEXT NOT NULL, policy_hash TEXT NOT NULL
);
CREATE TABLE priority_alerts (
 id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES priority_cases(id),
 assessment_id INTEGER NOT NULL REFERENCES priority_assessments(id),
 event_key TEXT NOT NULL UNIQUE, alert_type TEXT NOT NULL, title TEXT NOT NULL,
 created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'NOVO' CHECK(status IN ('NOVO','LIDO','ARQUIVADO','RESOLVIDO'))
);
CREATE TABLE priority_alert_history (
 id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL REFERENCES priority_alerts(id), created_at TEXT NOT NULL,
 action TEXT NOT NULL, before_status TEXT, after_status TEXT NOT NULL
);
CREATE TRIGGER priority_assessment_no_update BEFORE UPDATE ON priority_assessments BEGIN SELECT RAISE(ABORT,'Avaliação imutável'); END;
CREATE TRIGGER priority_assessment_no_delete BEFORE DELETE ON priority_assessments BEGIN SELECT RAISE(ABORT,'Avaliação imutável'); END;
CREATE TRIGGER priority_override_no_update BEFORE UPDATE ON priority_overrides BEGIN SELECT RAISE(ABORT,'Intervenção imutável'); END;
CREATE TRIGGER priority_override_no_delete BEFORE DELETE ON priority_overrides BEGIN SELECT RAISE(ABORT,'Intervenção imutável'); END;
CREATE TRIGGER priority_alert_history_no_update BEFORE UPDATE ON priority_alert_history BEGIN SELECT RAISE(ABORT,'Histórico imutável'); END;
CREATE TRIGGER priority_alert_history_no_delete BEFORE DELETE ON priority_alert_history BEGIN SELECT RAISE(ABORT,'Histórico imutável'); END;
