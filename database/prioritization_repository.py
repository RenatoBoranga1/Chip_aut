"""Priority storage and batched operational evidence; never modifies source decisions."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from database.dashboard_repository import DashboardRepository
from database.repository import SQLiteRepository, encode
from matching.review_policy import signature
from services.dashboard_service import flat, unknown


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


@contextmanager
def reading(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError("Banco não encontrado")
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN")
        yield db
    finally:
        db.close()


def installed(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='priority_cases'").fetchone())


def source_token(db, partner):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    values = []
    queries = [
        ("imports", "SELECT MAX(id) FROM imports", ()),
        (
            "partner_advertisements",
            "SELECT COUNT(*),MAX(last_seen_at),SUM(verification_count),SUM(not_seen_in_latest_collection),MAX(latest_collection_id) FROM partner_advertisements WHERE partner=?",
            (partner,),
        ),
        ("coverage_runs", "SELECT MAX(id) FROM coverage_runs", ()),
        ("review_decisions", "SELECT MAX(id) FROM review_decisions", ()),
        ("review_events", "SELECT MAX(id) FROM review_events", ()),
        ("matching_memory", "SELECT MAX(id) FROM matching_memory", ()),
        ("matching_reviews", "SELECT MAX(id) FROM matching_reviews", ()),
        ("development_events", "SELECT MAX(id) FROM development_events", ()),
        ("alerts", "SELECT MAX(id),MAX(last_seen_at) FROM alerts WHERE partner=?", (partner,)),
    ]
    for table, query, params in queries:
        values.append((table, tuple(db.execute(query, params).fetchone()) if table in tables else None))
    return digest(values)


def operational_sources(path, partner):
    # Reuse the canonical read-only evaluation of human memory; ancillary facts are loaded in batches.
    with DashboardRepository(path) as repo:
        db = repo.connection
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = db.execute(
            "SELECT external_id,payload_json,first_seen_at,last_seen_at,verification_count,latest_collection_id FROM partner_advertisements WHERE partner=? AND not_seen_in_latest_collection=0 ORDER BY external_id",
            (partner,),
        ).fetchall()
        reviews = {r["external_id"]: r for r in repo.queue(partner)}
        coverage = repo.automatic_coverage({r[5] for r in rows})
        situations = repo.partner_situations(partner)
        days = dict(
            db.execute(
                "SELECT external_id,count(DISTINCT substr(json_extract(payload_json,'$.collected_at'),1,10)) FROM partner_observations WHERE partner=? GROUP BY external_id",
                (partner,),
            )
        )
        decisions = dict(
            db.execute(
                "SELECT q.external_id,MAX(d.created_at) FROM review_decisions d JOIN review_items q ON q.id=d.review_item_id WHERE q.partner=? GROUP BY q.external_id",
                (partner,),
            )
        )
        development = {}
        if "development_origins" in tables:
            for r in db.execute(
                "SELECT o.external_id,d.id,d.status,d.status_since,d.updated_at,d.assigned_to,d.priority FROM development_origins o JOIN development_items d ON d.id=o.item_id WHERE o.partner=? ORDER BY d.id",
                (partner,),
            ):
                development[r[0]] = dict(
                    zip(("id", "status", "status_since", "updated_at", "assigned_to", "priority"), r[1:])
                )
        alerts = {}
        if "alerts" in tables:
            for ext, kind in db.execute(
                "SELECT DISTINCT external_id,alert_type FROM alerts WHERE partner=? AND condition_active=1 AND status IN ('NOVO','LIDO')",
                (partner,),
            ):
                alerts.setdefault(ext, set()).add(kind)
        sources = []
        for ext, payload, first, last, count, collection in rows:
            ad = json.loads(payload)
            review = reviews.get(ext)
            if review and review["signature"] != signature(ad):
                review = None
            saved = coverage.get((collection, ext))
            automatic = (
                review["automatic"]
                if review
                else saved["result"]
                if saved and saved["base_id"] == repo.base_id
                else unknown()
            )
            effective = review["effective"] if review else automatic
            ad.update(situations.get(ext, {}))
            row = flat(ad, automatic, effective, review, repo.base)
            row.pop("score", None)  # Matching similarity is not operational priority.
            row.update(
                identity_key=signature(ad),
                entity_id=ext,
                entity_type="advertisement",
                review_item_id=review["id"] if review else None,
                scanner_base_version=repo.base_id,
                source_snapshot_id=collection,
                first_seen=first,
                last_seen=last,
                observations=count,
                distinct_observation_days=max(days.get(ext, 0), 2 if count >= 2 and first[:10] != last[:10] else 1),
                pending_since=decisions.get(ext) or (review["created_at"] if review else first),
                last_human_at=decisions.get(ext),
                decision_stale=bool(review and review.get("stale_reason")),
                parse_warnings=ad.get("parse_warnings", []),
                development=development.get(ext),
                development_known="development_items" in tables,
                alert_types=sorted(alerts.get(ext, [])),
            )
            sources.append(row)
        return sources


class PrioritizationRepository(SQLiteRepository):
    def save(self, partner, source, result, origin):
        db = self.connection
        db.execute(
            "INSERT OR IGNORE INTO priority_cases(partner,entity_id,identity_key) VALUES (?,?,?)",
            (partner, source["entity_id"], source["identity_key"]),
        )
        row = db.execute(
            "SELECT id,latest_assessment_id FROM priority_cases WHERE partner=? AND entity_id=? AND identity_key=?",
            (partner, source["entity_id"], source["identity_key"]),
        ).fetchone()
        case_id, previous_id = row
        material = {k: v for k, v in result.items() if k != "calculated_at"}
        material_hash = digest(material)
        previous = db.execute(
            "SELECT material_hash,payload_json FROM priority_assessments WHERE id=?", (previous_id,)
        ).fetchone()
        changed = not previous or previous[0] != material_hash
        if changed:
            cursor = db.execute(
                "INSERT INTO priority_assessments(case_id,calculated_at,material_hash,origin,score,suggested_priority,confidence,policy_hash,payload_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    case_id,
                    result["calculated_at"],
                    material_hash,
                    origin,
                    result["score"],
                    result["suggested_priority"],
                    result["confidence"],
                    result["policy_hash"],
                    encode(result),
                ),
            )
            assessment_id = cursor.lastrowid
            db.execute(
                "UPDATE priority_cases SET latest_assessment_id=?,revision=revision+1 WHERE id=?",
                (assessment_id, case_id),
            )
        else:
            assessment_id = previous_id
        db.execute("UPDATE priority_cases SET active=1 WHERE id=?", (case_id,))
        return case_id, assessment_id, changed, json.loads(previous[1]) if previous else None

    def notify(self, case_id, assessment_id, kind, event_key, title, stamp):
        self.connection.execute(
            "INSERT OR IGNORE INTO priority_alerts(case_id,assessment_id,alert_type,event_key,title,created_at) VALUES (?,?,?,?,?,?)",
            (case_id, assessment_id, kind, event_key, title, stamp),
        )


def assessments(path, partner):
    with reading(path) as db:
        if not installed(db):
            return [], None, None
        rows = []
        for row in db.execute(
            "SELECT c.*,a.payload_json,a.calculated_at FROM priority_cases c JOIN priority_assessments a ON a.id=c.latest_assessment_id WHERE c.partner=? AND c.active=1 ORDER BY c.id",
            (partner,),
        ):
            item = dict(row)
            item.update(json.loads(item.pop("payload_json")))
            item["assessment_id"] = item["latest_assessment_id"]
            item["effective_priority"] = item["manual_priority"] or item["suggested_priority"]
            rows.append(item)
        maintenance = db.execute("SELECT * FROM priority_maintenance WHERE partner=?", (partner,)).fetchone()
        return rows, dict(maintenance) if maintenance else None, source_token(db, partner)


def assessment_history(path, case_id, partner, page=0):
    with reading(path) as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT a.id,a.calculated_at,a.origin,a.score,a.suggested_priority,a.payload_json FROM priority_assessments a JOIN priority_cases c ON c.id=a.case_id WHERE c.id=? AND c.partner=? ORDER BY a.id DESC LIMIT 20 OFFSET ?",
                (case_id, partner, page * 20),
            )
        ]


def override_history(path, case_id, partner):
    with reading(path) as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT o.* FROM priority_overrides o JOIN priority_cases c ON c.id=o.case_id WHERE c.id=? AND c.partner=? ORDER BY o.id DESC LIMIT 30",
                (case_id, partner),
            )
        ]


def development_assessments(path, item_id, partner):
    with reading(path) as db:
        if not installed(db):
            return []
        return db.execute(
            "SELECT DISTINCT c.id,a.score,a.suggested_priority,c.manual_priority FROM priority_cases c JOIN priority_assessments a ON a.id=c.latest_assessment_id JOIN development_origins o ON o.partner=c.partner AND o.external_id=c.entity_id WHERE o.item_id=? AND c.partner=? AND c.active=1",
            (item_id, partner),
        ).fetchall()
