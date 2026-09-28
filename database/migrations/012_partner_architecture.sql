-- Additive: historical executions and request keys belong to WR Motos.
ALTER TABLE pipeline_runs ADD COLUMN partner TEXT NOT NULL DEFAULT 'wr_motos';
ALTER TABLE pipeline_runs ADD COLUMN partner_request_key TEXT;
CREATE UNIQUE INDEX pipeline_partner_request ON pipeline_runs(partner, COALESCE(partner_request_key,request_key));
CREATE INDEX pipeline_partner_status ON pipeline_runs(partner,status,id);
CREATE TABLE scheduler_partners (
    partner TEXT PRIMARY KEY,
    heartbeat_at TEXT NOT NULL,
    next_run_at TEXT,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL
);
INSERT INTO scheduler_partners SELECT 'wr_motos',heartbeat_at,next_run_at,config_hash,status FROM scheduler_state;
