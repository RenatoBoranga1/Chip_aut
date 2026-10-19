"""Read-only operational snapshots also work before the optional migration is applied."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from database.repository import encode
from partners.integration import INTEGRATIONS, operational_modes


def now():
    return datetime.now(timezone.utc).isoformat()


def event(db, partner, action, reviewer, detail, external_id=None):
    db.execute(
        "INSERT INTO partner_operation_events(partner,external_id,created_at,action,reviewer,detail_json) VALUES (?,?,?,?,?,?)",
        (partner, external_id, now(), action, reviewer, encode(detail)),
    )


def alert(db, partner, code, active=True):
    stamp = now()
    if active:
        db.execute(
            "INSERT INTO partner_operation_alerts VALUES (?,?,?,?,1,1) ON CONFLICT(partner,code) DO UPDATE SET last_seen=excluded.last_seen,active=1,occurrences=partner_operation_alerts.occurrences+1",
            (partner, code, stamp, stamp),
        )
    else:
        db.execute(
            "UPDATE partner_operation_alerts SET active=0,last_seen=? WHERE partner=? AND code=?",
            (stamp, partner, code),
        )


def read_operations(database):
    result = {"partners": operational_modes(), "imports": [], "staging": [], "alerts": [], "mappings": {}, "events": []}
    last_imports = {}
    path = Path(database).resolve()
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "partner_staging" in tables:
                result["staging"] = [
                    dict(r) for r in db.execute("SELECT * FROM partner_staging ORDER BY last_seen DESC")
                ]
                for row in result["staging"]:
                    row["payload"] = json.loads(row.pop("payload_json"))
                    row["identity"] = json.loads(row.pop("identity_json"))
                result["imports"] = [
                    dict(r) for r in db.execute("SELECT * FROM partner_inventory_imports ORDER BY id DESC LIMIT 100")
                ]
                result["alerts"] = [
                    dict(r)
                    for r in db.execute("SELECT * FROM partner_operation_alerts WHERE active=1 ORDER BY partner,code")
                ]
                result["mappings"] = {
                    r[0]: json.loads(r[1])
                    for r in db.execute("SELECT partner,mapping_json FROM partner_import_mappings")
                }
                result["events"] = [
                    dict(r) for r in db.execute("SELECT * FROM partner_operation_events ORDER BY id DESC LIMIT 100")
                ]
                last_imports = dict(
                    db.execute("SELECT partner,MAX(created_at) FROM partner_inventory_imports GROUP BY partner")
                )
                result["imports_total"] = db.execute("SELECT count(*) FROM partner_inventory_imports").fetchone()[0]
            counts = (
                dict(
                    db.execute(
                        "SELECT partner,count(*) FROM partner_advertisements WHERE not_seen_in_latest_collection=0 GROUP BY partner"
                    )
                )
                if "partner_advertisements" in tables
                else {}
            )
    else:
        counts = {}
    for row in result["partners"]:
        key = row["partner_key"]
        row["active_ads"] = counts.get(key, 0)
        row["last_import"] = last_imports.get(key)
        row["pending_triage"] = sum(
            r["partner"] == key and r["classification"] in {"PENDING_CLASSIFICATION", "UNKNOWN"}
            for r in result["staging"]
        )
        row["status"] = (
            "ATIVO_COM_TRIAGEM"
            if row["requires_human_triage"]
            else "ATIVO_AUTOMATICO"
            if row["automation_enabled"]
            else "ATIVO_MANUAL"
        )
        row["auth_status"] = (
            "Aguardando credencial autorizada; importação por arquivo disponível"
            if key == "thomas_motos" and not row["requires_authentication"]
            else None
        )
    result["metrics"] = {
        "operational": len(INTEGRATIONS),
        "automatic": sum(p["automation_enabled"] for p in result["partners"]),
        "manual": sum(not p["automation_enabled"] and not p["requires_human_triage"] for p in result["partners"]),
        "with_triage": 1,
        "imports": result.get("imports_total", 0),
        "pending_triage": sum(r["classification"] in {"PENDING_CLASSIFICATION", "UNKNOWN"} for r in result["staging"]),
        "accepted": sum(r["classification"] == "MOTORCYCLE" for r in result["staging"]),
        "discarded": sum(r["classification"] in {"KART", "SERVICE"} for r in result["staging"]),
    }
    return result
