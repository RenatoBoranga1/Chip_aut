"""Operational execution history, separate from immutable human decisions."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from database.repository import SQLiteRepository, encode
from services.scheduler_config import utcnow


class PipelineRepository(SQLiteRepository):
    def start(self, trigger, config_hash, request_key=None, status="RUNNING"):
        stamp = utcnow().isoformat()
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO pipeline_runs(request_key,started_at,heartbeat_at,trigger_type,status,config_hash) VALUES (?,?,?,?,?,?)",
                (request_key, stamp, stamp, trigger, status, config_hash),
            )
        return cursor.lastrowid

    def existing(self, key):
        if not key:
            return None
        row = self.connection.execute("SELECT id FROM pipeline_runs WHERE request_key=?", (key,)).fetchone()
        return row[0] if row else None

    def recover(self):
        stamp = utcnow().isoformat()
        # Called ONLY while holding the OS execution lock, never merely on an expired heartbeat.
        with self.connection:
            self.connection.execute(
                "UPDATE pipeline_runs SET status='CANCELLED',finished_at=?,duration_seconds=MAX(0,(julianday(?)-julianday(started_at))*86400),error_summary=? WHERE status='RUNNING'",
                (stamp, stamp, "Processo anterior encerrado; bloqueio recuperado com segurança"),
            )

    def beat(self, run_id):
        with self.connection:
            self.connection.execute(
                "UPDATE pipeline_runs SET heartbeat_at=? WHERE id=? AND status='RUNNING'",
                (utcnow().isoformat(), run_id),
            )

    def finish(self, run_id, status, seconds, summary, error=None, collection_id=None, fingerprint=None):
        with self.connection:
            self.connection.execute(
                "UPDATE pipeline_runs SET status=?,finished_at=?,duration_seconds=?,summary_json=?,error_summary=?,collection_run_id=?,fingerprint=? WHERE id=?",
                (status, utcnow().isoformat(), seconds, encode(summary), error, collection_id, fingerprint, run_id),
            )

    def refresh_observations(self, result):
        if result.cached:
            return
        with self.connection:
            for ad in result.advertisements:
                self.connection.execute(
                    "UPDATE partner_advertisements SET last_seen_at=?,verification_count=verification_count+1 "
                    "WHERE partner=? AND external_id=? AND julianday(last_seen_at)<julianday(?)",
                    (ad.collected_at, ad.partner, ad.external_id, ad.collected_at),
                )

    def scheduler(self, config, due, status):
        with self.connection:
            self.connection.execute(
                "INSERT INTO scheduler_state VALUES (1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET heartbeat_at=excluded.heartbeat_at,next_run_at=excluded.next_run_at,config_hash=excluded.config_hash,status=excluded.status",
                (utcnow().isoformat(), due.isoformat() if due else None, config.digest, status),
            )


def read_pipeline(database, limit=30, offset=0, run_id=None):
    path = Path(database).resolve()
    if not path.is_file():
        return {"runs": [], "scheduler": None}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='pipeline_runs'").fetchone():
            return {"runs": [], "scheduler": None}
        if run_id is None:
            rows = db.execute("SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        else:
            rows = db.execute("SELECT * FROM pipeline_runs WHERE id=?", (run_id,))
        runs = []
        for row in rows:
            item = dict(row)
            item["summary"] = json.loads(item.pop("summary_json"))
            runs.append(item)
        state = db.execute("SELECT * FROM scheduler_state WHERE id=1").fetchone()
        return {"runs": runs, "scheduler": dict(state) if state else None}
