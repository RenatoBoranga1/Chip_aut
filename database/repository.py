import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from scanner_base.models import ParsedBase
from scanner_base.normalizer import normalize_text


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def snapshot_diff(previous: dict, current: dict) -> dict:
    old_keys, new_keys = set(previous), set(current)
    status_changes = []
    systems_added, systems_removed = [], []
    fields = ("supported_systems", "unsupported_systems", "analysis_systems", "unknown_systems")
    for key in sorted(old_keys | new_keys):
        old, new = previous.get(key, {}), current.get(key, {})
        if old and new and old["status"] != new["status"]:
            status_changes.append({"key": key, "before": old["status"], "after": new["status"]})
        before = {normalize_text(v) for field in fields for v in old.get(field, [])}
        after = {normalize_text(v) for field in fields for v in new.get(field, [])}
        systems_added.extend({"key": key, "system": v} for v in sorted(after - before))
        systems_removed.extend({"key": key, "system": v} for v in sorted(before - after))
    return {
        "motorcycles_added": sorted(new_keys - old_keys),
        "motorcycles_removed": sorted(old_keys - new_keys),
        "status_changes": status_changes,
        "systems_added": systems_added,
        "systems_removed": systems_removed,
    }


class SQLiteRepository:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        try:
            for migration in sorted((Path(__file__).parent / "migrations").glob("[0-9]*_*.sql")):
                version = int(migration.name.split("_", 1)[0])
                has_table = self.connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
                ).fetchone()
                if (
                    has_table
                    and self.connection.execute("SELECT 1 FROM schema_version WHERE version=?", (version,)).fetchone()
                ):
                    continue
                self.connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + migration.read_text(encoding="utf-8")
                    + f"\nINSERT OR IGNORE INTO schema_version VALUES ({version});\nCOMMIT;"
                )
        except Exception:
            self.connection.rollback()
            self.connection.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    def latest_snapshot(self) -> dict:
        rows = self.connection.execute(
            "SELECT m.normalized_key, s.payload_json FROM motorcycle_snapshots s "
            "JOIN motorcycles m ON m.id = s.motorcycle_id "
            "WHERE s.import_id = (SELECT MAX(id) FROM imports)"
        )
        return {key: json.loads(payload) for key, payload in rows}

    def save_import(self, base: ParsedBase, source: str, digest: str, rules: dict, report: dict) -> tuple[int, dict]:
        db = self.connection
        # Acquire the write lock before reading the previous version.
        with db:
            db.execute("BEGIN IMMEDIATE")
            current = {m.key: asdict(m) for m in base.motorcycles}
            diff = snapshot_diff(self.latest_snapshot(), current)
            cursor = db.execute(
                "INSERT INTO imports(created_at,source_path,source_sha256,policy_json,report_json,diff_json) "
                "VALUES (?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), source, digest, encode(rules), encode(report), encode(diff)),
            )
            import_id = cursor.lastrowid
            ids = {}
            for key, payload in current.items():
                db.execute(
                    "INSERT OR IGNORE INTO motorcycles(normalized_key,first_import_id) VALUES (?,?)", (key, import_id)
                )
                motorcycle_id = db.execute("SELECT id FROM motorcycles WHERE normalized_key=?", (key,)).fetchone()[0]
                ids[key] = motorcycle_id
                db.execute(
                    "INSERT INTO motorcycle_snapshots VALUES (?,?,?,?)",
                    (import_id, motorcycle_id, payload["status"], encode(payload)),
                )
            db.executemany(
                "INSERT INTO system_records(import_id,motorcycle_id,sheet,source_row,payload_json) VALUES (?,?,?,?,?)",
                [(import_id, ids[r.key], r.sheet, r.row, encode(asdict(r))) for r in base.records],
            )
            db.executemany(
                "INSERT INTO import_issues(import_id,code,payload_json) VALUES (?,?,?)",
                [(import_id, issue["code"], encode(issue)) for issue in base.issues],
            )
        return import_id, diff
