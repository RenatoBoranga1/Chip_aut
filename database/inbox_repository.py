"""Read-only inbox access, including compatibility with databases before migration 016."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path


def read_inbox(database, partner=None, identifier=None, limit=200):
    path = Path(database).resolve()
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='partner_inbox'").fetchone():
            return []
        clauses, args = [], []
        for key, val in (("partner", partner), ("id", identifier)):
            if val is not None:
                clauses.append(key + "=?")
                args.append(val)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = [
            dict(r)
            for r in db.execute("SELECT * FROM partner_inbox" + where + " ORDER BY id DESC LIMIT ?", (*args, limit))
        ]
        for row in rows:
            for key in ("mapping", "preview"):
                row[key] = json.loads(row.pop(key + "_json"))
            row.pop("stat_json")
        return rows


def read_inbox_errors(database, partner):
    path = Path(database).resolve()
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='partner_inbox_errors'").fetchone():
            return []
        return [
            dict(r)
            for r in db.execute(
                "SELECT filename,error,updated_at FROM partner_inbox_errors WHERE partner=? AND active=1 ORDER BY updated_at DESC LIMIT 200",
                (partner,),
            )
        ]
