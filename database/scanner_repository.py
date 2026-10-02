"""Scanner preparation and audit. No SQL in the UI; reads never migrate."""

import hashlib
import json
from pathlib import PureWindowsPath

from database.development_repository import read_connection
from database.repository import SQLiteRepository, encode
from matching.review_policy import target_identity
from scanner_base.adapters import conflict_diagnostics
from scanner_base.models import Motorcycle
from services.scheduler_config import utcnow


def installed(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='scanner_versions'").fetchone())


def active_import(db):
    return db.execute("SELECT MAX(id) FROM imports").fetchone()[0]


def decision_token(db):
    values = []
    for table in ("review_decisions", "matching_memory", "development_events"):
        values.append(db.execute(f"SELECT COUNT(*),MAX(id) FROM {table}").fetchone())
    return hashlib.sha256(encode([list(v) for v in values]).encode()).hexdigest()


def snapshot(db, identifier):
    return {
        json.loads(r[0])["key"]: json.loads(r[0])
        for r in db.execute("SELECT payload_json FROM motorcycle_snapshots WHERE import_id=?", (identifier,))
    }


def records(db, identifier):
    return [
        json.loads(r[0]) for r in db.execute("SELECT payload_json FROM system_records WHERE import_id=?", (identifier,))
    ]


def event(db, version, actor, action, notes, payload=None):
    db.execute(
        "INSERT INTO scanner_events(version_id,created_at,actor,action,notes,payload_json) VALUES (?,?,?,?,?,?)",
        (version, utcnow().isoformat(), actor, action, notes, encode(payload or {})),
    )


def register_import(db, import_id, source, digest, report, prepared=None):
    """Every legacy import stays visible; imports.MAX(id) remains the single active reference."""
    stamp = utcnow().isoformat()
    db.execute("UPDATE scanner_versions SET status='SUPERSEDED' WHERE status='PUBLISHED'")
    if prepared is None:
        cur = db.execute(
            "INSERT INTO scanner_versions(original_filename,sha256,imported_at,published_at,imported_by,status,import_id,total_records,valid_records,unique_vehicles,invalid_records,report_json) VALUES (?,?,?,?,?,'PUBLISHED',?,?,?,?,?,?)",
            (
                PureWindowsPath(source).name,
                digest,
                stamp,
                stamp,
                "Importação administrativa",
                import_id,
                report.get("valid_system_records", 0) + report.get("rejected_rows", 0),
                report.get("valid_system_records", 0),
                db.execute("SELECT COUNT(*) FROM motorcycle_snapshots WHERE import_id=?", (import_id,)).fetchone()[0],
                report.get("rejected_rows", 0),
                encode(report),
            ),
        )
        prepared = cur.lastrowid
        event(
            db, prepared, "Importação administrativa", "LEGACY_IMPORT", "Importação pelo fluxo administrativo existente"
        )
    else:
        db.execute(
            "UPDATE scanner_versions SET status='PUBLISHED',published_at=?,import_id=? WHERE id=?",
            (stamp, import_id, prepared),
        )
    return prepared


def impacts(db, new, changed):
    rows = []
    for (item_id,) in db.execute("SELECT id FROM review_items WHERE active=1"):
        # Reuse the official decision scope (including shared decisions).
        from database.review_repository import ReviewRepository

        repo = object.__new__(ReviewRepository)
        repo.connection = db
        item = repo._item(item_id)
        events = repo._decisions(item)
        if not events:
            continue
        d = events[-1]
        candidate = new.get(d["candidate_key"])
        reason = "VALID"
        if d["action"] in {"NAO_EXISTE_NA_BASE", "REJEITAR_CANDIDATO"}:
            reason = "REVALIDATE"
        elif d["action"] == "CONFIRMAR_MATCH":
            if candidate is None or target_identity(Motorcycle(**candidate)) != json.loads(d["target_identity_json"]):
                reason = "TARGET_REMOVED"
            elif d["candidate_key"] in changed:
                reason = "SUPPORT_CHANGED"
        elif d["action"] == "DEIXAR_PENDENTE":
            reason = "PENDING"
        rows.append(
            (
                "REVIEW",
                item_id,
                {"decision_id": d["id"], "review_id": item_id, "reason": reason, "candidate": d["candidate_key"]},
            )
        )
    for row in db.execute(
        "SELECT id,scanner_key,manufacturer,model,version,year,status FROM development_items WHERE status NOT IN ('COMPLETED','DISCARDED')"
    ):
        from matching.fuzzy_matcher import combined_model
        from scanner_base.normalizer import normalized_key

        key = row[1] or normalized_key(row[2], combined_model(row[3], row[4] or ""), row[5])
        if key in new and (key in changed):
            rows.append(
                (
                    "DEVELOPMENT",
                    row[0],
                    {
                        "item_id": row[0],
                        "key": key,
                        "message": "Possivelmente atendida pela nova versão da base; presença não confirma suporte",
                    },
                )
            )
    return rows


class ScannerRepository(SQLiteRepository):
    pass


def overview(path, page=0, size=20):
    with read_connection(path) as db:
        active = active_import(db)
        if not installed(db):
            r = db.execute("SELECT id,created_at,source_sha256 FROM imports ORDER BY id DESC LIMIT 1").fetchone()
            return {
                "active_import": active,
                "current": dict(r) if r else None,
                "versions": [],
                "total": 0,
                "installed": False,
            }
        fields = "id,original_filename,sha256,imported_at,published_at,imported_by,status,total_records,valid_records,unique_vehicles,invalid_records,notes,parent_import_id,import_id"
        values = [
            dict(r)
            for r in db.execute(
                f"SELECT {fields} FROM scanner_versions ORDER BY id DESC LIMIT ? OFFSET ?", (size, max(0, page) * size)
            )
        ]
        for v in values:
            v["original_filename"] = PureWindowsPath(v["original_filename"]).name
        return {
            "active_import": active,
            "current": next(
                (dict(r) for r in db.execute(f"SELECT {fields} FROM scanner_versions WHERE import_id=?", (active,))),
                None,
            ),
            "versions": values,
            "total": db.execute("SELECT COUNT(*) FROM scanner_versions").fetchone()[0],
            "installed": True,
        }


def detail(path, version, page=0, kind=None):
    with read_connection(path) as db:
        if not installed(db):
            raise ValueError("Nenhuma preparação registrada")
        r = db.execute(
            "SELECT id,original_filename,sha256,imported_at,published_at,imported_by,status,total_records,valid_records,unique_vehicles,invalid_records,notes,parent_import_id,import_id,report_json,impact_token FROM scanner_versions WHERE id=?",
            (version,),
        ).fetchone()
        if not r:
            raise ValueError("Versão não encontrada")
        value = dict(r)
        for k in ("content", "payload_json", "policy_json"):
            value.pop(k, None)
        value["original_filename"] = PureWindowsPath(value["original_filename"]).name
        value["report"] = json.loads(value.pop("report_json"))
        # Older V16 reports counted support conflicts only. Project diagnostics from
        # their saved issues without reparsing Excel or mutating historical reports.
        report = value["report"]
        if report.get("format") == "APPLICATION_GENERAL" and "application_conflicts" not in report:
            issues = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT j.value FROM scanner_versions v,json_each(v.payload_json,'$.issues') j "
                    "WHERE v.id=? AND json_extract(j.value,'$.code') IN ('APPLICATION_VARIANT','CONFLICTING_SYSTEM')",
                    (version,),
                )
            ]
            if not issues and value["import_id"] is not None:
                issues = [
                    json.loads(row[0])
                    for row in db.execute(
                        "SELECT payload_json FROM import_issues WHERE import_id=? "
                        "AND code IN ('APPLICATION_VARIANT','CONFLICTING_SYSTEM')",
                        (value["import_id"],),
                    )
                ]
            report.update(conflict_diagnostics(issues))
            value["diagnostics_recomputed"] = True

        where = "version_id=?" + (" AND kind=?" if kind else "")
        args = (version, kind) if kind else (version,)
        value["differences"] = [
            dict(r) | {"payload": json.loads(r["payload_json"])}
            for r in db.execute(
                "SELECT * FROM scanner_differences WHERE " + where + " ORDER BY id LIMIT 30 OFFSET ?",
                (*args, max(page, 0) * 30),
            )
        ]
        value["differences_total"] = db.execute(
            "SELECT COUNT(*) FROM scanner_differences WHERE " + where, args
        ).fetchone()[0]
        value["impacts"] = [
            dict(r) | {"payload": json.loads(r["payload_json"])}
            for r in db.execute(
                "SELECT * FROM scanner_impacts WHERE version_id=? ORDER BY id LIMIT 30 OFFSET ?",
                (version, max(page, 0) * 30),
            )
        ]
        value["impacts_total"] = db.execute(
            "SELECT COUNT(*) FROM scanner_impacts WHERE version_id=?", (version,)
        ).fetchone()[0]
        value["events"] = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM scanner_events WHERE version_id=? ORDER BY id DESC LIMIT 30 OFFSET ?",
                (version, max(page, 0) * 30),
            )
        ]
        job = db.execute("SELECT status,attempts,message FROM scanner_jobs WHERE version_id=?", (version,)).fetchone()
        value["validation_issues"] = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT j.value FROM scanner_versions v,json_each(v.payload_json,'$.issues') j WHERE v.id=? LIMIT 30 OFFSET ?",
                (version, max(page, 0) * 30),
            )
        ]
        value["job"] = dict(job) if job else None
        return value
