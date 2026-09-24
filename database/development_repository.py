"""Development persistence and bounded reads; no scanner/review writes."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from database.dashboard_repository import DashboardRepository
from database.repository import SQLiteRepository, encode


def unpack(row):
    if row is None:
        raise ValueError("Item de desenvolvimento não encontrado")
    value = dict(row)
    for key in list(value):
        if key.endswith("_json"):
            value[key[:-5]] = json.loads(value.pop(key))
    return value


@contextmanager
def read_connection(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    try:
        yield db
    finally:
        db.close()


def exists(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='development_items'").fetchone())


def source_snapshot(path, partner, kind, identifier):
    """Resolve persisted, CURRENT evidence; caller cannot supply support or identity."""
    alert_id = None
    with DashboardRepository(path) as repo:
        if kind == "alert":
            row = repo.connection.execute(
                "SELECT review_item_id,external_id FROM alerts WHERE id=? AND partner=?", (identifier, partner)
            ).fetchone()
            if not row or not row[1]:
                raise ValueError("Alerta sem anúncio apropriado para desenvolvimento")
            alert_id = int(identifier)
            kind, identifier = ("review", row[0]) if row[0] else ("advertisement", row[1])
        if kind == "review":
            item = repo.detail(int(identifier), partner)
            if not item["active"]:
                raise ValueError("Identidade antiga: abra a revisão atual do anúncio")
            ad = item["advertisement"]
            ad.update(first_seen=item["first_seen"], last_seen=item["last_seen"])
            effective, review_id, priority = item["effective"], item["id"], item["priority"]
        elif kind == "advertisement":
            ads = repo.advertisements(partner)
            ad = next((a for a in ads if a["external_id"] == str(identifier)), None)
            if ad is None:
                raise ValueError("Anúncio não encontrado no estoque atual")
            review = next((r for r in repo.queue(partner) if r["external_id"] == str(identifier)), None)
            if review:
                effective, review_id, priority = review["effective"], review["id"], review["priority"]
            else:
                coverage = repo.automatic_coverage({ad["collection_id"]}).get((ad["collection_id"], ad["external_id"]))
                effective = (
                    coverage["result"]
                    if coverage and coverage["base_id"] == repo.base_id
                    else {"match_type": "AGUARDANDO_MATCHING", "requires_review": True}
                )
                review_id, priority = None, "medium"
        elif kind == "scanner":
            moto = repo.base.get(str(identifier))
            if not moto:
                raise ValueError("Moto não encontrada na versão atual da base")
            ad = {**asdict(moto), "partner": "scanner", "external_id": moto.key, "version": None}
            effective = {
                "match_type": "EXATO_NORMALIZADO",
                "scanner_key": moto.key,
                "scanner_status": moto.status,
                "requires_review": False,
            }
            review_id, priority = None, "medium"
        else:
            raise ValueError("Origem de desenvolvimento inválida")
        ad = {k: v for k, v in ad.items() if k not in {"raw_data", "raw_text"}}
        target = repo.base.get(effective.get("scanner_key")) if not effective.get("requires_review", True) else None
        return {
            "advertisement": ad,
            "effective": effective,
            "scanner": asdict(target) if target else None,
            "base_version": repo.base_id,
            "review_item_id": review_id,
            "alert_id": alert_id,
            "priority": priority,
        }


class DevelopmentRepository(SQLiteRepository):
    def one(self, item_id):
        cursor = self.connection.execute("SELECT * FROM development_items WHERE id=?", (item_id,))
        row = cursor.fetchone()
        return unpack(dict(zip([c[0] for c in cursor.description], row)) if row else None)

    def active(self, key):
        row = self.connection.execute(
            "SELECT id FROM development_items WHERE identity_key=? AND status NOT IN ('COMPLETED','DISCARDED')", (key,)
        ).fetchone()
        return row[0] if row else None

    def replay(self, key, digest):
        row = self.connection.execute(
            "SELECT payload_hash,item_id FROM development_commands WHERE command_key=?", (key,)
        ).fetchone()
        if row and row[0] != digest:
            raise ValueError("Solicitação já utilizada com outros dados")
        return row[1] if row else None

    def remember(self, key, digest, item_id):
        self.connection.execute("INSERT INTO development_commands VALUES (?,?,?)", (key, digest, item_id))

    def insert(self, values):
        names = list(values)
        return self.connection.execute(
            "INSERT INTO development_items(" + ",".join(names) + ") VALUES (" + ",".join("?" for _ in names) + ")",
            tuple(values.values()),
        ).lastrowid

    def update(self, item_id, values):
        allowed = {
            "status",
            "priority",
            "assigned_to",
            "updated_at",
            "status_since",
            "completed_at",
            "discarded_at",
            "completion_version",
            "technical_json",
            "checklist_json",
            "revision",
            "last_seen_at",
            "primary_image_url",
        }
        if not set(values) <= allowed:
            raise ValueError("Campos de desenvolvimento inválidos")
        self.connection.execute(
            "UPDATE development_items SET " + ",".join(k + "=?" for k in values) + " WHERE id=?",
            (*values.values(), item_id),
        )

    def event(self, item_id, actor, action, before, after, note, stamp):
        return self.connection.execute(
            "INSERT INTO development_events(item_id,created_at,actor,action,before_json,after_json,justification) VALUES (?,?,?,?,?,?,?)",
            (item_id, stamp, actor, action, encode(before), encode(after), note),
        ).lastrowid

    def origin(self, item_id, source, actor, stamp):
        had_origin = self.connection.execute(
            "SELECT 1 FROM development_origins WHERE item_id=? LIMIT 1", (item_id,)
        ).fetchone()
        ad = source["advertisement"]
        origin_key = encode([ad["partner"], ad["external_id"]])
        observation = encode(
            [
                origin_key,
                ad.get("collected_at") or ad.get("last_seen"),
                source["base_version"],
                source.get("alert_id"),
                source.get("review_item_id"),
            ]
        )
        changed = self.connection.execute(
            "INSERT OR IGNORE INTO development_occurrences(item_id,observation_key,created_at,actor,payload_json) VALUES (?,?,?,?,?)",
            (item_id, observation, stamp, actor, encode(source)),
        ).rowcount
        if not changed:
            return False
        first = ad.get("first_seen") or ad.get("collected_at") or stamp
        last = ad.get("last_seen") or ad.get("collected_at") or stamp
        self.connection.execute(
            "INSERT INTO development_origins(item_id,origin_key,partner,external_id,review_item_id,alert_id,first_seen_at,last_seen_at,payload_json) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(item_id,origin_key) DO UPDATE SET first_seen_at=MIN(first_seen_at,excluded.first_seen_at),last_seen_at=MAX(last_seen_at,excluded.last_seen_at),occurrence_count=occurrence_count+1,payload_json=excluded.payload_json,alert_id=COALESCE(excluded.alert_id,alert_id)",
            (
                item_id,
                origin_key,
                ad["partner"],
                ad["external_id"],
                source["review_item_id"],
                source["alert_id"],
                first,
                last,
                encode(source),
            ),
        )
        if had_origin:
            self.connection.execute(
                "UPDATE development_items SET first_seen_at=MIN(first_seen_at,?),last_seen_at=MAX(last_seen_at,?),primary_image_url=CASE WHEN ? >= last_seen_at THEN COALESCE(?,primary_image_url) ELSE primary_image_url END,updated_at=?,revision=revision+1 WHERE id=?",
                (first, last, last, ad.get("primary_image_url"), stamp, item_id),
            )
        return True

    def last_scan(self):
        row = self.connection.execute("SELECT checked_at FROM development_maintenance WHERE id=1").fetchone()
        return row[0] if row else None

    def status_dates(self, status):
        return self.connection.execute(
            "SELECT id,status_since FROM development_items WHERE status=?", (status,)
        ).fetchall()

    def save_scan(self, stamp):
        self.connection.execute(
            "INSERT INTO development_maintenance VALUES (1,?) ON CONFLICT(id) DO UPDATE SET checked_at=excluded.checked_at",
            (stamp,),
        )

    def notify(self, item_id, kind, event_key, severity, title, message, stamp):
        cur = self.connection.execute(
            "INSERT OR IGNORE INTO development_alerts(item_id,event_key,alert_type,severity,title,message,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (item_id, event_key, kind, severity, title, message, stamp, stamp),
        )
        if cur.rowcount:
            self.connection.execute(
                "INSERT INTO development_alert_history(alert_id,created_at,action,after_status) VALUES (?,?,'CRIADO','NOVO')",
                (cur.lastrowid, stamp),
            )
        return bool(cur.rowcount)


def list_items(path, filters=None, text="", sort="priority", page=0, size=8):
    if type(page) is not int or page < 0 or type(size) is not int or not 1 <= size <= 50:
        raise ValueError("Paginação inválida")
    conditions, params = [], []
    for key, values in (filters or {}).items():
        if not values:
            continue
        if key in {"status", "priority", "assigned_to", "manufacturer", "year", "reason"}:
            conditions.append(f"d.{key} IN (" + ",".join("?" for _ in values) + ")")
            params.extend(values)
        elif key == "partner":
            conditions.append(
                "EXISTS(SELECT 1 FROM development_origins o WHERE o.item_id=d.id AND o.partner IN ("
                + ",".join("?" for _ in values)
                + "))"
            )
            params.extend(values)
        elif key == "photo" and values in (["with"], ["without"]):
            conditions.append("COALESCE(d.primary_image_url,'')" + ("<>''" if values == ["with"] else "=''"))
        else:
            raise ValueError("Filtro de desenvolvimento inválido")
    if text.strip():
        conditions.append(
            "instr(lower(d.manufacturer||' '||d.model||' '||COALESCE(d.version,'')||' '||d.assigned_to||' '||d.year),lower(?))>0"
        )
        params.append(text.strip())
    orders = {
        "priority": "CASE d.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,d.updated_at DESC,d.id",
        "recent": "d.updated_at DESC,d.id DESC",
        "oldest": "d.created_at,d.id",
        "model": "d.manufacturer,d.model,d.year,d.id",
        "status": "d.status,d.id",
    }
    if sort not in orders:
        raise ValueError("Ordenação inválida")
    with read_connection(path) as db:
        if not exists(db):
            return {"items": [], "total": 0, "metrics": {}, "facets": {}, "installed": False}
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        total = db.execute("SELECT count(*) FROM development_items d" + where, params).fetchone()[0]
        # No histories, notes or source snapshots in the paginated list.
        fields = "id,manufacturer,model,version,year,reason,status,priority,assigned_to,created_at,updated_at,status_since,first_seen_at,last_seen_at,primary_image_url,revision"
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT "
                + ",".join("d." + k for k in fields.split(","))
                + ", (SELECT group_concat(DISTINCT partner) FROM development_origins WHERE item_id=d.id) AS partners FROM development_items d"
                + where
                + " ORDER BY "
                + orders[sort]
                + " LIMIT ? OFFSET ?",
                (*params, size, page * size),
            )
        ]
        metrics = {r[0]: r[1] for r in db.execute("SELECT status,count(*) FROM development_items GROUP BY status")}
        metrics["active"] = sum(v for k, v in metrics.items() if k not in {"COMPLETED", "DISCARDED"})
        metrics["high"] = db.execute(
            "SELECT count(*) FROM development_items WHERE priority='high' AND status NOT IN ('COMPLETED','DISCARDED')"
        ).fetchone()[0]
        facets = {
            key: [r[0] for r in db.execute(f"SELECT DISTINCT {key} FROM development_items ORDER BY {key}")]
            for key in ("manufacturer", "year", "assigned_to")
        }
        facets["partner"] = [
            r[0] for r in db.execute("SELECT DISTINCT partner FROM development_origins ORDER BY partner")
        ]
        return {"items": rows, "total": total, "metrics": metrics, "facets": facets, "installed": True}


def read_item(path, item_id, page=0):
    if type(page) is not int or page < 0:
        raise ValueError("Paginação inválida")
    with read_connection(path) as db:
        if not exists(db):
            raise ValueError("Gestão de desenvolvimento ainda não inicializada")
        item = unpack(db.execute("SELECT * FROM development_items WHERE id=?", (item_id,)).fetchone())
        item["history"] = [
            unpack(r)
            for r in db.execute(
                "SELECT * FROM development_events WHERE item_id=? ORDER BY id DESC LIMIT 30 OFFSET ?",
                (item_id, page * 30),
            )
        ]
        item["history_count"] = db.execute(
            "SELECT count(*) FROM development_events WHERE item_id=?", (item_id,)
        ).fetchone()[0]
        item["origins"] = [
            unpack(r)
            for r in db.execute(
                "SELECT * FROM development_origins WHERE item_id=? ORDER BY id LIMIT 30 OFFSET ?", (item_id, page * 30)
            )
        ]
        item["origin_count"] = db.execute(
            "SELECT count(*) FROM development_origins WHERE item_id=?", (item_id,)
        ).fetchone()[0]
        item["alerts"] = [
            dict(r)
            for r in db.execute(
                "SELECT id,title,status FROM development_alerts WHERE item_id=? ORDER BY id DESC LIMIT 30 OFFSET ?",
                (item_id, page * 30),
            )
        ]
        return item


def find_active(path, identity_key):
    with read_connection(path) as db:
        if not exists(db):
            return None
        row = db.execute(
            "SELECT id FROM development_items WHERE identity_key=? AND status NOT IN ('COMPLETED','DISCARDED')",
            (identity_key,),
        ).fetchone()
        return row[0] if row else None
