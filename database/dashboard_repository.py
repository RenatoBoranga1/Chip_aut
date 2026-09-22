"""Read-only dashboard queries. Browsing does not migrate or update SQLite."""

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from database.review_repository import ReviewRepository
from matching.review_policy import load_policy, priority


class DashboardRepository(ReviewRepository):
    def __init__(self, path):
        path = Path(path).resolve()
        if not path.is_file():
            raise ValueError("Banco não encontrado. Configure MOTO_DB e importe a base primeiro.")
        self.connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
        self.connection.execute("PRAGMA query_only=ON")
        self.connection.execute("BEGIN")
        version = self.connection.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        if version < 6:
            self.connection.close()
            raise ValueError("Banco anterior à fila operacional. Execute a atualização pela CLI.")
        self.base_id, self.scanner_policy, self.motos = self.matching_snapshot()
        self.base = {m.key: m for m in self.motos}

    def partners(self):
        return [
            r[0] for r in self.connection.execute("SELECT DISTINCT partner FROM partner_collections ORDER BY partner")
        ]

    def preview(self, item):
        effective, state, decision, stale = self._evaluate(item, self.base_id, self.base)
        return {
            **item,
            "effective": effective,
            "state": state,
            "priority": priority(effective, state, load_policy()),
            "human_decision": decision,
            "stale_reason": stale,
            "revision": self.revision(item, self.base_id),
            "base_id": self.base_id,
        }

    def queue(self, partner):
        cursor = self.connection.execute(
            "SELECT id,partner,external_id,signature,identity_json,active,state,priority,collection_id,run_id,last_seen,created_at,updated_at,"
            "json_remove(advertisement_json,'$.raw_data','$.raw_text') AS advertisement_json,automatic_json "
            "FROM review_items WHERE partner=? AND active=1 ORDER BY id",
            (partner,),
        )
        results = []
        for row in cursor.fetchall():
            item = dict(zip((c[0] for c in cursor.description), row))
            for field in ("identity", "advertisement", "automatic"):
                item[field] = json.loads(item.pop(field + "_json"))
            results.append(self.preview(item))
        return results

    def advertisements(self, partner):
        return [
            {**json.loads(row[0]), "first_seen": row[1], "last_seen": row[2], "collection_id": row[3]}
            for row in self.connection.execute(
                "SELECT json_remove(payload_json,'$.raw_data','$.raw_text'),first_seen_at,last_seen_at,latest_collection_id "
                "FROM partner_advertisements WHERE partner=? AND not_seen_in_latest_collection=0 ORDER BY external_id",
                (partner,),
            )
        ]

    def automatic_coverage(self, collection_ids):
        if not collection_ids:
            return {}
        placeholders = ",".join("?" for _ in collection_ids)
        rows = self.connection.execute(
            "SELECT c.collection_id,c.import_id,json_extract(i.value,'$.advertisement.external_id'),json_extract(i.value,'$.matching') "
            "FROM coverage_runs c, json_each(c.report_json,'$.groups') g, json_each(g.value) i "
            f"WHERE c.id IN (SELECT MAX(id) FROM coverage_runs WHERE collection_id IN ({placeholders}) GROUP BY collection_id)",
            tuple(collection_ids),
        )
        return {(r[0], r[2]): {"base_id": r[1], "result": json.loads(r[3])} for r in rows}

    def collections(self, partner, limit=50, offset=0):
        rows = self.connection.execute(
            "SELECT id,created_at,status,json_remove(summary_json,'$.advertisements'),"
            "(SELECT count(*) FROM partner_observations o WHERE o.collection_id=c.id),json_array_length(summary_json,'$.advertisements') "
            "FROM partner_collections c WHERE partner=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (partner, limit, offset),
        )
        return [
            {
                "id": r[0],
                "created_at": r[1],
                "status": r[2],
                "summary": json.loads(r[3]),
                "count": r[5] if r[5] is not None else r[4],
            }
            for r in rows
        ]

    def collection_warnings(self, collection_id):
        return dict(
            self.connection.execute(
                "SELECT w.value,COUNT(*) FROM ("
                "SELECT payload_json AS payload FROM partner_observations WHERE collection_id=? "
                "UNION ALL SELECT a.value FROM partner_collections c,json_each(c.summary_json,'$.advertisements') a "
                "WHERE c.id=? AND NOT EXISTS (SELECT 1 FROM partner_observations WHERE collection_id=c.id)"
                ") source,json_each(source.payload,'$.parse_warnings') w GROUP BY w.value",
                (collection_id, collection_id),
            ).fetchall()
        )

    def collection_delta(self, collection_id, partner):
        previous = self.connection.execute(
            "SELECT MAX(id) FROM partner_collections WHERE partner=? AND id<? AND status='COMPLETE'",
            (partner, collection_id),
        ).fetchone()[0]

        def ids(cid):
            return {
                r[0]
                for r in self.connection.execute(
                    "SELECT external_id FROM partner_observations WHERE collection_id=?", (cid,)
                )
            }

        current, before = ids(collection_id), ids(previous)
        status = self.connection.execute(
            "SELECT status FROM partner_collections WHERE id=?", (collection_id,)
        ).fetchone()[0]
        if status == "CACHED":
            return {"new": None, "reappeared": None, "disappeared": None}
        return {
            "new": len(current - before),
            "reappeared": len(current & before),
            "disappeared": len(before - current) if status == "COMPLETE" else None,
        }

    def history(self, partner, limit=30, offset=0):
        transitions = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='review_decision_transitions'"
        ).fetchone()
        extra = "t.before_state,t.after_state" if transitions else "NULL AS before_state,NULL AS after_state"
        join = " LEFT JOIN review_decision_transitions t ON t.decision_id=d.id" if transitions else ""
        cursor = self.connection.execute(
            f"SELECT d.id,d.review_item_id,d.action,d.reviewer,d.note,d.created_at,d.import_id,d.candidate_key,{extra} "
            f"FROM review_decisions d JOIN review_items q ON q.id=d.review_item_id {join} WHERE q.partner=? ORDER BY d.id DESC LIMIT ? OFFSET ?",
            (partner, limit, offset),
        )
        decisions = [dict(zip((c[0] for c in cursor.description), row)) for row in cursor.fetchall()]
        cursor = self.connection.execute(
            "SELECT o.id,o.review_item_id,o.collection_id,o.run_id,o.import_id,o.created_at "
            "FROM review_occurrences o JOIN review_items q ON q.id=o.review_item_id WHERE q.partner=? ORDER BY o.id DESC LIMIT ? OFFSET ?",
            (partner, limit, offset),
        )
        occurrences = [dict(zip((c[0] for c in cursor.description), row)) for row in cursor.fetchall()]
        return {"decisions": decisions, "occurrences": occurrences}

    def detail(self, item_id, partner):
        item = self._item(item_id)
        if item["partner"] != partner:
            raise ValueError("Item não pertence ao parceiro selecionado")
        item = self.preview(item)
        item["advertisement"].pop("raw_data", None)
        item["history"] = self._decisions(item)
        if self.connection.execute("SELECT 1 FROM sqlite_master WHERE name='review_decision_transitions'").fetchone():
            for decision in item["history"]:
                transition = self.connection.execute(
                    "SELECT before_state,after_state FROM review_decision_transitions WHERE decision_id=?",
                    (decision["id"],),
                ).fetchone()
                decision["before_state"], decision["after_state"] = transition or (None, None)
        item["systems"] = (
            asdict(self.base[item["effective"]["scanner_key"]])
            if item["effective"]["scanner_key"] in self.base
            else None
        )
        seen = self.connection.execute(
            "SELECT first_seen_at,last_seen_at FROM partner_advertisements WHERE partner=? AND external_id=?",
            (partner, item["external_id"]),
        ).fetchone()
        item["first_seen"] = seen[0] if seen else item["created_at"]
        item["events"] = self.connection.execute(
            "SELECT created_at,reason FROM review_events WHERE review_item_id=? ORDER BY id DESC LIMIT 50", (item_id,)
        ).fetchall()
        return item
