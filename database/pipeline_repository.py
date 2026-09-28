"""Operational execution history, separate from immutable human decisions."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from database.repository import SQLiteRepository, encode
from services.scheduler_config import utcnow


class PipelineRepository(SQLiteRepository):
    def start(self, trigger, config_hash, request_key=None, status="RUNNING", partner="wr_motos"):
        stamp = utcnow().isoformat()
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO pipeline_runs(partner_request_key,started_at,heartbeat_at,trigger_type,status,config_hash,partner) VALUES (?,?,?,?,?,?,?)",
                (request_key, stamp, stamp, trigger, status, config_hash, partner),
            )
        return cursor.lastrowid

    def existing(self, key, partner="wr_motos"):
        if not key:
            return None
        row = self.connection.execute(
            "SELECT id FROM pipeline_runs WHERE partner=? AND COALESCE(partner_request_key,request_key)=?",
            (partner, key),
        ).fetchone()
        return row[0] if row else None

    def recover(self, partner="wr_motos"):
        stamp = utcnow().isoformat()
        # Called ONLY while holding the OS execution lock, never merely on an expired heartbeat.
        with self.connection:
            self.connection.execute(
                "UPDATE pipeline_runs SET status='CANCELLED',finished_at=?,duration_seconds=MAX(0,(julianday(?)-julianday(started_at))*86400),error_summary=? WHERE status='RUNNING' AND partner=?",
                (stamp, stamp, "Processo anterior encerrado; bloqueio recuperado com segurança", partner),
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

    def scheduler(self, config, due, status, partner="wr_motos"):
        with self.connection:
            self.connection.execute(
                "INSERT INTO scheduler_partners VALUES (?,?,?,?,?) ON CONFLICT(partner) DO UPDATE SET heartbeat_at=excluded.heartbeat_at,next_run_at=excluded.next_run_at,config_hash=excluded.config_hash,status=excluded.status",
                (partner, utcnow().isoformat(), due.isoformat() if due else None, config.digest, status),
            )


def read_pipeline(database, limit=30, offset=0, run_id=None, partner="wr_motos"):
    path = Path(database).resolve()
    if not path.is_file():
        return {"runs": [], "scheduler": None}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        columns = {r[1] for r in db.execute("PRAGMA table_info(pipeline_runs)")}
        if not columns or ("partner" not in columns and partner != "wr_motos"):
            return {"runs": [], "scheduler": None}
        where, args = ("partner=?", [partner]) if "partner" in columns else ("1=1", [])
        if run_id is not None:
            where += " AND id=?"
            args.append(run_id)
        rows = db.execute(
            f"SELECT * FROM pipeline_runs WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?", (*args, limit, offset)
        )
        runs = []
        for row in rows:
            item = dict(row)
            item.setdefault("partner", "wr_motos")
            item["request_key"] = item.pop("partner_request_key", None) or item["request_key"]
            item["summary"] = json.loads(item.pop("summary_json"))
            runs.append(item)
        if "partner" in columns:
            state = db.execute("SELECT * FROM scheduler_partners WHERE partner=?", (partner,)).fetchone()
        else:
            state = db.execute("SELECT * FROM scheduler_state WHERE id=1").fetchone()
        return {"runs": runs, "scheduler": dict(state) if state else None}
