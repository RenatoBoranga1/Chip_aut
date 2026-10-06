"""Capability-limited reads. No inheritance from operational command repositories."""

import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from scanner_base.normalizer import normalize_text


def read_authorizer(action, first, second, database, trigger):
    if action == sqlite3.SQLITE_FUNCTION and str(second).lower() in {"load_extension", "readfile", "writefile"}:
        return sqlite3.SQLITE_DENY
    return (
        sqlite3.SQLITE_OK
        if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
        else sqlite3.SQLITE_DENY
    )


class AIRepository:
    def __init__(self, database):
        self._path = Path(database).resolve()

    @contextmanager
    def _reading(self):
        with closing(sqlite3.connect(self._path.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
            try:
                db.row_factory = sqlite3.Row
                db.create_function("normal", 1, lambda value: normalize_text(value or ""), deterministic=True)
                db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN")
                db.set_authorizer(read_authorizer)
                yield db
            finally:
                db.set_authorizer(None)
                db.close()

    @staticmethod
    def _active(db):
        return db.execute(
            "SELECT import_id FROM scanner_versions WHERE status='PUBLISHED' AND import_id IS NOT NULL"
        ).fetchone()

    def get_counts(self):
        with self._reading() as db:
            row = self._active(db)
            if not row:
                return None
            base = row[0]
            vehicles = db.execute("SELECT count(*) FROM motorcycle_snapshots WHERE import_id=?", (base,)).fetchone()[0]
            applications, systems = db.execute(
                "SELECT count(*),count(DISTINCT json_extract(payload_json,'$.system_key')) FROM system_records WHERE import_id=?",
                (base,),
            ).fetchone()
            return {"base_id": base, "vehicles": vehicles, "applications": applications, "systems": systems}

    def search_scanner(self, terms, limit=20, vehicle_id=None):
        limit = max(1, min(int(limit), 50))
        with self._reading() as db:
            active = self._active(db)
            if not active:
                return {"items": [], "total": 0, "base_id": None}
            conditions = ["s.import_id=?"]
            params = [active[0]]
            if vehicle_id is not None:
                conditions.append("m.id=?")
                params.append(int(vehicle_id))
            for term in terms[:12]:
                conditions.append(
                    "instr(normal(json_extract(s.payload_json,'$.manufacturer')||' '||"
                    "json_extract(s.payload_json,'$.model')||' '||json_extract(s.payload_json,'$.year')),?)>0"
                )
                params.append(normalize_text(term))
            where = " AND ".join(conditions)
            joined = " FROM motorcycle_snapshots s JOIN motorcycles m ON m.id=s.motorcycle_id WHERE " + where
            total = db.execute("SELECT count(*)" + joined, params).fetchone()[0]
            rows = db.execute(
                "SELECT m.id,s.payload_json" + joined + " ORDER BY m.normalized_key LIMIT ?", (*params, limit)
            ).fetchall()
            fields = ("key", "manufacturer", "model", "year", "status", "record_count", "system_count")
            items = [{"id": r[0], **{k: json.loads(r[1]).get(k) for k in fields}} for r in rows]
            return {"items": items, "total": total, "base_id": active[0]}

    def get_vehicle(self, identifier):
        return self.search_scanner([], 1, identifier)

    def get_vehicle_applications(self, identifier, limit=20):
        with self._reading() as db:
            active = self._active(db)
            if not active:
                return {"items": [], "total": 0, "base_id": None}
            params = (active[0], int(identifier))
            total = db.execute(
                "SELECT count(*) FROM system_records WHERE import_id=? AND motorcycle_id=?", params
            ).fetchone()[0]
            rows = db.execute(
                "SELECT id,payload_json FROM system_records WHERE import_id=? AND motorcycle_id=? ORDER BY id LIMIT ?",
                (*params, max(1, min(int(limit), 50))),
            ).fetchall()
            fields = ("system", "cable", "cable_location", "status", "test_type", "application_attributes")
            return {
                "base_id": active[0],
                "total": total,
                "items": [{"id": r[0], **{k: json.loads(r[1]).get(k) for k in fields}} for r in rows],
            }

    def get_base_versions(self, limit=20):
        with self._reading() as db:
            total = db.execute("SELECT count(*) FROM scanner_versions").fetchone()[0]
            rows = db.execute(
                "SELECT id,import_id,status,imported_at,published_at,unique_vehicles FROM scanner_versions ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 50)),),
            )
            return {"total": total, "items": [dict(r) for r in rows]}
