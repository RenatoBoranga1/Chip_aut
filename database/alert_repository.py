"""Alert persistence; no matching or human decision mutations."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from database.repository import SQLiteRepository, encode
from services.scheduler_config import utcnow


class AlertRepository(SQLiteRepository):
    def history(self, alert_id, action, before, after):
        self.connection.execute(
            "INSERT INTO alert_history(alert_id,created_at,action,before_status,after_status) VALUES (?,?,?,?,?)",
            (alert_id, utcnow().isoformat(), action, before, after),
        )

    def observe(self, event, run, event_key):
        stamp = run["finished_at"]
        key = event["deduplication_key"]
        row = self.connection.execute(
            "SELECT id,status,condition_active FROM alerts WHERE deduplication_key=?", (key,)
        ).fetchone()
        fields = (
            "alert_type",
            "severity",
            "partner",
            "external_id",
            "manufacturer",
            "scanner_key",
            "review_item_id",
            "title",
            "message",
        )
        values = [event.get(f) for f in fields]
        details = encode(event["details"])
        if row:
            alert_id, status, active = row
            if self.connection.execute(
                "SELECT 1 FROM alert_occurrences WHERE alert_id=? AND event_key=?", (alert_id, event_key)
            ).fetchone():
                return "unchanged"
            if not active:
                self.history(alert_id, "REABERTO", status, "NOVO")
                self.connection.execute(
                    "UPDATE alerts SET status='NOVO',read_at=NULL,archived_at=NULL,resolved_at=NULL WHERE id=?",
                    (alert_id,),
                )
            self.connection.execute(
                "UPDATE alerts SET "
                + ",".join(f"{f}=?" for f in fields)
                + ",pipeline_run_id=?,collection_run_id=?,details_json=?,updated_at=?,last_seen_at=?,occurrence_count=occurrence_count+1,condition_active=1 WHERE id=?",
                (*values, run["id"], run["collection_run_id"], details, stamp, stamp, alert_id),
            )
            outcome = "updated"
        else:
            cursor = self.connection.execute(
                "INSERT INTO alerts(deduplication_key,"
                + ",".join(fields)
                + ",pipeline_run_id,collection_run_id,details_json,created_at,updated_at,first_seen_at,last_seen_at) VALUES ("
                + ",".join("?" for _ in range(17))
                + ")",
                (key, *values, run["id"], run["collection_run_id"], details, stamp, stamp, stamp, stamp),
            )
            alert_id = cursor.lastrowid
            self.history(alert_id, "CRIADO", None, "NOVO")
            outcome = "created"
        self.connection.execute(
            "INSERT INTO alert_occurrences(alert_id,event_key,pipeline_run_id,created_at,details_json) VALUES (?,?,?,?,?)",
            (alert_id, event_key, run["id"], stamp, details),
        )
        return outcome

    def clear_conditions(self, types, active_keys, partner="wr_motos"):
        for kind in types:
            for alert_id, key, state in self.connection.execute(
                "SELECT id,deduplication_key,status FROM alerts WHERE partner=? AND alert_type=? AND condition_active=1",
                (partner, kind),
            ).fetchall():
                if key not in active_keys:
                    self.connection.execute(
                        "UPDATE alerts SET condition_active=0,updated_at=? WHERE id=?", (utcnow().isoformat(), alert_id)
                    )
                    self.history(alert_id, "CONDICAO_ENCERRADA", state, state)

    def transition(self, alert_id, target, partner):
        if target not in {"NOVO", "LIDO", "ARQUIVADO", "RESOLVIDO"}:
            raise ValueError("Situação do alerta inválida")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT status FROM alerts WHERE id=? AND partner=?", (alert_id, partner)
            ).fetchone()
            if not row:
                raise ValueError("Alerta não encontrado para este parceiro")
            before = row[0]
            if target == before:
                return
            if before in {"ARQUIVADO", "RESOLVIDO"} and target == "LIDO":
                raise ValueError("Reabra o alerta antes de marcar como lido")
            stamp = utcnow().isoformat()
            self.connection.execute(
                "UPDATE alerts SET status=?,updated_at=?,read_at=?,archived_at=?,resolved_at=? WHERE id=?",
                (
                    target,
                    stamp,
                    stamp if target == "LIDO" else None,
                    stamp if target == "ARQUIVADO" else None,
                    stamp if target == "RESOLVIDO" else None,
                    alert_id,
                ),
            )
            action = {
                "LIDO": "LIDO",
                "ARQUIVADO": "ARQUIVADO",
                "RESOLVIDO": "RESOLVIDO",
                "NOVO": "REABERTO" if before in {"ARQUIVADO", "RESOLVIDO"} else "NAO_LIDO",
            }[target]
            self.history(alert_id, action, before, target)


def read_alerts(database, partner=None):
    path = Path(database).resolve()
    if not path.is_file():
        return {"alerts": [], "pending": 0}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='alerts'").fetchone():
            return {"alerts": [], "pending": 0}
        rows = db.execute(
            "SELECT * FROM alerts" + (" WHERE partner=?" if partner else ""), (partner,) if partner else ()
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            result.append(item)
        pending = db.execute("SELECT COUNT(*) FROM alert_deliveries WHERE processed_at IS NULL").fetchone()[0]
        return {"alerts": result, "pending": pending}


def read_alert_history(database, alert_id, partner):
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [
            dict(r)
            for r in db.execute(
                "SELECT h.* FROM alert_history h JOIN alerts a ON a.id=h.alert_id WHERE a.id=? AND a.partner=? ORDER BY h.id",
                (alert_id, partner),
            )
        ]
