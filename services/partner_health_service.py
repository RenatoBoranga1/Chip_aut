"""Freshness and efficiency are read-only facts; alerts are explicit idempotent maintenance."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from database.inventory_repository import event, read_operations
from database.partner_repository import PartnerRepository
from services.partner_inventory_import import writable
from services.partner_operations_config import load_policy

ALERTS = (
    "PARTNER_FILE_WAITING",
    "PARTNER_FILE_INVALID",
    "PARTNER_IMPORT_STALE",
    "PARTNER_IMPORT_ANOMALY",
    "PARTNER_TRIAGE_PENDING",
    "PARTNER_TRIAGE_STALE",
)


def partner_health(database, *, clock=None):
    current = (clock or (lambda: datetime.now(timezone.utc)))()
    operations = read_operations(database)
    policy = load_policy()
    path = Path(database).resolve()
    inbox, staging_time, metrics = {}, None, {"observed": 0, "reused": 0}
    wr_time = None
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "partner_collections" in tables:
                wr_time = db.execute(
                    "SELECT MAX(created_at) FROM partner_collections WHERE partner='wr_motos' AND status IN ('COMPLETE','PARTIAL')"
                ).fetchone()[0]
            if "partner_inbox" in tables:
                for partner, status, preview in db.execute("SELECT partner,status,preview_json FROM partner_inbox"):
                    item = inbox.setdefault(partner, {"waiting": 0, "invalid": 0, "anomalies": 0})
                    item["waiting"] += status in {"DETECTED", "VALIDATING", "READY_FOR_REVIEW"}
                    item["invalid"] += status == "INVALID"
                    item["anomalies"] += status == "READY_FOR_REVIEW" and any(
                        w["level"] == "ATENÇÃO" for w in json.loads(preview).get("anomalies", [])
                    )
                for key, count in db.execute(
                    "SELECT partner,count(*) FROM partner_inbox_errors WHERE active=1 GROUP BY partner"
                ):
                    item = inbox.setdefault(key, {"waiting": 0, "invalid": 0, "anomalies": 0})
                    item["invalid"] += count
            if "partner_operation_events" in tables:
                staging_time = db.execute(
                    "SELECT MAX(created_at) FROM partner_operation_events WHERE partner='motonil' AND action='STAGING_COLLECTED'"
                ).fetchone()[0]
                for (raw,) in db.execute(
                    "SELECT detail_json FROM partner_operation_events WHERE partner='motonil' AND action='STAGING_COLLECTED'"
                ):
                    detail = json.loads(raw)
                    metrics["observed"] += detail.get("observed", 0)
                    metrics["reused"] += detail.get("reused_decisions", detail.get("accepted_from_memory", 0))
    rows = []
    for p in operations["partners"]:
        key = p["partner_key"]
        pending = inbox.get(key, {"waiting": 0, "invalid": 0, "anomalies": 0})
        updated = staging_time if key == "motonil" else p["last_import"]
        if key == "wr_motos":
            rows.append(
                {
                    "partner": key,
                    "name": p["display_name"],
                    "health": "Política de coleta existente",
                    "last_update": wr_time,
                    "days": max(0, (current - datetime.fromisoformat(wr_time)).days) if wr_time else None,
                    **pending,
                    "pending_triage": 0,
                    "alerts": [],
                }
            )
            continue
        days = max(0, (current - datetime.fromisoformat(updated)).days) if updated else None
        stale = days is not None and days >= policy[key]["stale_after_days"]
        codes = []
        if pending["waiting"]:
            codes.append("PARTNER_FILE_WAITING")
        if pending["invalid"]:
            codes.append("PARTNER_FILE_INVALID")
        if pending["anomalies"]:
            codes.append("PARTNER_IMPORT_ANOMALY")
        if p["pending_triage"]:
            codes.append("PARTNER_TRIAGE_PENDING")
        if stale:
            codes.append("PARTNER_TRIAGE_STALE" if key == "motonil" else "PARTNER_IMPORT_STALE")
        failed = any(
            a["partner"] == key and a["code"] in {"SOURCE_UNAVAILABLE", "AUTH_FAILED", "IMPORT_FAILED"}
            for a in operations["alerts"]
        )
        health = (
            "Desatualizado"
            if stale
            else "Atenção"
            if pending["invalid"] or pending["anomalies"] or failed
            else "Aguardando ação"
            if not updated or pending["waiting"] or p["pending_triage"]
            else "Saudável"
        )
        rows.append(
            {
                "partner": key,
                "name": p["display_name"],
                "health": health,
                "last_update": updated,
                "days": days,
                **pending,
                "pending_triage": p["pending_triage"],
                "alerts": codes,
            }
        )
    metrics["reuse_percent"] = round(100 * metrics["reused"] / metrics["observed"], 1) if metrics["observed"] else 0
    return {
        "partners": rows,
        "efficiency": metrics,
        "waiting": sum(r["waiting"] for r in rows),
        "invalid": sum(r["invalid"] for r in rows),
    }


def refresh_health(database, *, clock=None):
    writable(database)
    data = partner_health(database, clock=clock)
    stamp = (clock or (lambda: datetime.now(timezone.utc)))().isoformat()
    with PartnerRepository(database) as repo, repo.connection:
        db = repo.connection
        for row in data["partners"]:
            key = row["partner"]
            if key == "wr_motos":
                continue
            for code in ALERTS:
                active = code in row["alerts"]
                old = db.execute(
                    "SELECT active FROM partner_operation_alerts WHERE partner=? AND code=?", (key, code)
                ).fetchone()
                if active and not old:
                    db.execute("INSERT INTO partner_operation_alerts VALUES (?,?,?,?,1,1)", (key, code, stamp, stamp))
                elif old and bool(old[0]) != active:
                    db.execute(
                        "UPDATE partner_operation_alerts SET active=?,last_seen=?,occurrences=occurrences+? WHERE partner=? AND code=?",
                        (int(active), stamp, int(active), key, code),
                    )
                if active and (not old or not old[0]) and code.endswith("STALE"):
                    event(db, key, "STALE_WARNING", "sistema", {"code": code, "days": row["days"]})
            db.execute(
                "INSERT INTO partner_health_state VALUES (?,?,?) ON CONFLICT(partner) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at WHERE status!=excluded.status",
                (key, row["health"], stamp),
            )
    return data
