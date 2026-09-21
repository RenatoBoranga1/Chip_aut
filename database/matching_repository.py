import json
from dataclasses import asdict
from datetime import datetime, timezone

from database.repository import SQLiteRepository, encode
from matching.models import MatchResult
from scanner_base.models import Motorcycle


class MatchingRepository(SQLiteRepository):
    def matching_snapshot(self):
        row = self.connection.execute("SELECT id,policy_json FROM imports ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            raise ValueError("Nenhuma base importada: execute python -m app.import_base primeiro")
        import_id, policy = row
        payloads = self.connection.execute(
            "SELECT payload_json FROM motorcycle_snapshots WHERE import_id=? ORDER BY motorcycle_id", (import_id,)
        )
        motorcycles = [Motorcycle(**json.loads(payload)) for (payload,) in payloads]
        return import_id, json.loads(policy), motorcycles

    def save_match(self, import_id: int, policy: dict, result: MatchResult) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO matching_runs(created_at,import_id,policy_json,result_json,requires_review) "
                "VALUES (?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    import_id,
                    encode(policy),
                    encode(asdict(result)),
                    int(result.requires_review),
                ),
            )
        return cursor.lastrowid

    def load_memory(self):
        memory = {}
        for query_key, scanner_key, decision in self.connection.execute(
            "SELECT query_key,scanner_key,decision FROM matching_memory ORDER BY id"
        ):
            memory.setdefault(query_key, {})[scanner_key] = decision
        return memory

    def save_matches(self, import_id, policy, results):
        ids = []
        with self.connection:
            for result in results:
                cursor = self.connection.execute(
                    "INSERT INTO matching_runs(created_at,import_id,policy_json,result_json,requires_review) VALUES (?,?,?,?,?)",
                    (
                        datetime.now(timezone.utc).isoformat(),
                        import_id,
                        encode(policy),
                        encode(asdict(result)),
                        int(result.requires_review),
                    ),
                )
                ids.append(cursor.lastrowid)
        return ids

    def remember_match(self, run_id, scanner_key, decision, reviewer, note):
        if decision not in {"CONFIRMAR", "REJEITAR", "REVOGAR"} or not reviewer.strip() or not note.strip():
            raise ValueError("Decisão, revisor e justificativa inválidos")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            run = self.get_match(run_id)
            key = run["automatic_result"]["normalized_key"]
            if not key:
                raise ValueError("Corrija a identidade incompleta antes de criar uma regra persistente")
            if decision != "REVOGAR" and scanner_key not in {
                c["scanner_key"] for c in run["automatic_result"]["candidates"]
            }:
                raise ValueError("Selecione um dos candidatos exibidos")
            if decision == "CONFIRMAR":
                # Only one active positive rule per query; retain revoked history.
                for previous, state in self.load_memory().get(key, {}).items():
                    if state == "CONFIRMAR" and previous != scanner_key:
                        self._memory_event(key, previous, "REVOGAR", run_id, reviewer, note)
            self._memory_event(key, scanner_key, decision, run_id, reviewer, note)
        return {"run_id": run_id, "query_key": key, "scanner_key": scanner_key, "decision": decision}

    def _memory_event(self, key, scanner_key, decision, run_id, reviewer, note):
        self.connection.execute(
            "INSERT INTO matching_memory(query_key,scanner_key,decision,source_run_id,reviewer,note,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                key,
                scanner_key,
                decision,
                run_id,
                reviewer.strip(),
                note.strip(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def get_match(self, run_id: int) -> dict:
        row = self.connection.execute(
            "SELECT id,created_at,import_id,policy_json,result_json FROM matching_runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Matching {run_id} não encontrado")
        result = {
            "run_id": row[0],
            "created_at": row[1],
            "import_id": row[2],
            "policy": json.loads(row[3]),
            "automatic_result": json.loads(row[4]),
        }
        reviews = self.connection.execute(
            "SELECT id,created_at,reviewer,decision,scanner_key,note FROM matching_reviews WHERE run_id=? ORDER BY id",
            (run_id,),
        )
        result["reviews"] = [
            dict(zip(("id", "created_at", "reviewer", "decision", "scanner_key", "note"), r)) for r in reviews
        ]
        latest_import = self.connection.execute("SELECT MAX(id) FROM imports").fetchone()[0]
        result["is_current_base"] = result["import_id"] == latest_import
        automatic = result["automatic_result"]
        result["effective_result"] = {
            "match_type": automatic["match_type"],
            "scanner_key": automatic["scanner_key"],
            "scanner_status": automatic["scanner_status"],
            "requires_review": automatic["requires_review"],
            "confidence": automatic["confidence"],
        }
        if result["reviews"]:
            review = result["reviews"][-1]
            selected = next((c for c in automatic["candidates"] if c["scanner_key"] == review["scanner_key"]), None)
            result["effective_result"] = {
                "match_type": "CONFIRMADO_MANUALMENTE" if selected else "SEM_CORRESPONDENCIA_MANUAL",
                "scanner_key": selected["scanner_key"] if selected else None,
                "scanner_status": selected["scanner_status"] if selected else "NAO_ENCONTRADA_NA_BASE",
                "requires_review": False,
                "confidence": None,
            }
        return result

    def pending_matches(self) -> list[dict]:
        rows = self.connection.execute(
            "SELECT r.id FROM matching_runs r WHERE r.requires_review=1 AND NOT EXISTS "
            "(SELECT 1 FROM matching_reviews v WHERE v.run_id=r.id) ORDER BY r.id"
        ).fetchall()
        return [self.get_match(row[0]) for row in rows]

    def review_match(self, run_id: int, scanner_key: str | None, reviewer: str, note: str) -> dict:
        if not reviewer.strip() or not note.strip():
            raise ValueError("Revisor e justificativa são obrigatórios")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            run = self.get_match(run_id)
            if scanner_key is not None and scanner_key not in {
                c["scanner_key"] for c in run["automatic_result"]["candidates"]
            }:
                raise ValueError("A chave deve pertencer aos candidatos exibidos nesta execução")
            self.connection.execute(
                "INSERT INTO matching_reviews(run_id,created_at,reviewer,decision,scanner_key,note) VALUES (?,?,?,?,?,?)",
                (
                    run_id,
                    datetime.now(timezone.utc).isoformat(),
                    reviewer.strip(),
                    "CONFIRMAR" if scanner_key is not None else "SEM_CORRESPONDENCIA",
                    scanner_key,
                    note.strip(),
                ),
            )
        return self.get_match(run_id)
