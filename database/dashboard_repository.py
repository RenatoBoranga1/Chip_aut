"""Read-only dashboard queries. Browsing does not migrate or update SQLite."""

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from database.review_repository import ReviewRepository
from database.vehicle_images import latest_vehicle_image
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
            item["advertisement"].update(latest_vehicle_image(self.connection, item["advertisement"]))
            results.append(self.preview(item))
        return results

    def advertisements(self, partner):
        rows = [
            {**json.loads(row[0]), "first_seen": row[1], "last_seen": row[2], "collection_id": row[3]}
            for row in self.connection.execute(
                "SELECT json_remove(payload_json,'$.raw_data','$.raw_text'),first_seen_at,last_seen_at,latest_collection_id "
                "FROM partner_advertisements WHERE partner=? AND not_seen_in_latest_collection=0 ORDER BY external_id",
                (partner,),
            )
        ]
        for ad in rows:
            ad.update(latest_vehicle_image(self.connection, ad))
        return rows

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

    def partner_situations(self, partner):
        """State at the latest actual observation; cached/failed runs are not stock evidence."""
        latest = self.connection.execute(
            "SELECT MAX(id) FROM partner_collections WHERE partner=? AND status IN ('COMPLETE','PARTIAL')",
            (partner,),
        ).fetchone()[0]
        previous = self.connection.execute(
            "SELECT MAX(id) FROM partner_collections WHERE partner=? AND status='COMPLETE' AND id<?",
            (partner, latest),
        ).fetchone()[0]
        seen = {
            r[0]: r[1:]
            for r in self.connection.execute(
                "SELECT external_id,MIN(collection_id),MAX(collection_id=?),MAX(collection_id=?) "
                "FROM partner_observations WHERE partner=? GROUP BY external_id",
                (latest, previous, partner),
            )
        }
        reused = False
        if self.connection.execute("SELECT 1 FROM sqlite_master WHERE name='pipeline_runs'").fetchone():
            run = self.connection.execute(
                "SELECT p.collection_run_id,json_extract(p.summary_json,'$.reused') FROM pipeline_runs p "
                "JOIN partner_collections c ON c.id=p.collection_run_id WHERE c.partner=? "
                "AND p.status IN ('SUCCESS','PARTIAL_SUCCESS') ORDER BY p.id DESC LIMIT 1",
                (partner,),
            ).fetchone()
            reused = bool(run and run[0] == latest and run[1])
        result = {}
        for external_id, missing, first, last in self.connection.execute(
            "SELECT external_id,not_seen_in_latest_collection,first_seen_at,last_seen_at "
            "FROM partner_advertisements WHERE partner=?",
            (partner,),
        ):
            first_collection, in_latest, in_previous = seen.get(external_id, (None, False, False))
            state = "Já conhecido"
            if missing:
                state = "Saiu do estoque"
            elif in_latest and not reused:
                if first_collection == latest:
                    state = "Novo anúncio"
                elif previous and not in_previous and first_collection < previous:
                    state = "Reapareceu"
            result[external_id] = {"partner_status": state, "first_seen": first, "last_seen": last}
        return result

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
        item["advertisement"].update(latest_vehicle_image(self.connection, item["advertisement"]))
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
