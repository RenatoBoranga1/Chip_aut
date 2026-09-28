"""Read-only operational metrics grouped by configured partner."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from database.pipeline_repository import read_pipeline
from partners.registry import PartnerRegistry


def partner_status(database, registry=None):
    registry = registry or PartnerRegistry()
    result = []
    path = Path(database).resolve()
    for entry in registry.list():
        row = {
            "partner": entry.partner_key,
            "display_name": entry.display_name,
            "enabled": entry.enabled,
            "last_collection": None,
            "status": None,
            "active_ads": 0,
            "recent_errors": 0,
        }
        if path.is_file():
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "partner_collections" in tables:
                    last = db.execute(
                        "SELECT created_at,status,summary_json FROM partner_collections WHERE partner=? ORDER BY id DESC LIMIT 1",
                        (entry.partner_key,),
                    ).fetchone()
                    if last:
                        row.update(
                            last_collection=last[0],
                            status=last[1],
                            recent_errors=len(json.loads(last[2]).get("errors", [])),
                        )
                    row["active_ads"] = db.execute(
                        "SELECT COUNT(*) FROM partner_advertisements WHERE partner=? AND not_seen_in_latest_collection=0",
                        (entry.partner_key,),
                    ).fetchone()[0]
            runs = read_pipeline(database, limit=30, partner=entry.partner_key)["runs"]
            if runs:
                row["status"] = runs[0]["status"]
                row["recent_errors"] = sum(
                    len(r["summary"].get("errors", [])) or bool(r["error_summary"]) for r in runs
                )
        result.append(row)
    return result
