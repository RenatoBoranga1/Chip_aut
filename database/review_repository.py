"""Transactional operational queue. Source observations and decisions are immutable."""

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone

from database.matching_repository import MatchingRepository
from database.repository import encode
from matching.review_policy import (
    ACTIONS,
    SHARED_ACTIONS,
    complete_identity,
    identity,
    load_policy,
    memory_scope,
    needs_attention,
    priority,
    signature,
    target_identity,
)
from partners.models import PartnerMotorcycle


def now():
    return datetime.now(timezone.utc).isoformat()


class ReviewRepository(MatchingRepository):
    def _item(self, item_id):
        cursor = self.connection.execute("SELECT * FROM review_items WHERE id=?", (item_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError("Item de revisão não encontrado")
        result = dict(zip((c[0] for c in cursor.description), row))
        for field in ("identity", "advertisement", "automatic", "effective"):
            result[field] = json.loads(result.pop(field + "_json"))
        return result

    def _decisions(self, item):
        # Incomplete identities never share memory, even with each other.
        shared = complete_identity(item["identity"])
        cursor = self.connection.execute(
            "SELECT * FROM review_decisions WHERE review_item_id=? OR "
            "(? AND signature=? AND action IN ('CONFIRMAR_MATCH','REJEITAR_CANDIDATO','NAO_EXISTE_NA_BASE')) ORDER BY id",
            (item["id"], int(shared), item["signature"]),
        )
        events = [dict(zip((c[0] for c in cursor.description), row)) for row in cursor.fetchall()]
        return [
            event
            for event in events
            if event["review_item_id"] == item["id"]
            or (
                json.loads(event["policy_json"]).get("memory_scope") == "identity"
                and (event["action"] == "NAO_EXISTE_NA_BASE" or item["automatic"]["match_type"] != "AMBIGUOUS")
            )
        ]

    def _event(self, item_id, base_id, decision_id, reason):
        self.connection.execute(
            "INSERT INTO review_events(review_item_id,created_at,import_id,decision_id,reason) VALUES (?,?,?,?,?)",
            (item_id, now(), base_id, decision_id, reason),
        )

    def _evaluate(self, item, base_id, base):
        automatic = item["automatic"]
        effective = deepcopy(automatic)
        state, stale = "pending", None
        decisions = self._decisions(item)
        decision = decisions[-1] if decisions else None
        run_base = self.connection.execute(
            "SELECT import_id FROM matching_runs WHERE id=?", (item["run_id"],)
        ).fetchone()[0]
        if run_base != base_id:
            effective.update(
                match_type="REVISAR", scanner_key=None, scanner_status=None, confidence=None, requires_review=True
            )
            effective["reasons"] = ["Base atualizada; resultado automático histórico requer novo matching."]
        if decision:
            action = decision["action"]
            target = base.get(decision["candidate_key"])
            if action == "CONFIRMAR_MATCH":
                if target is None or target_identity(target) != json.loads(decision["target_identity_json"]):
                    stale = "STALE_TARGET_REMOVED_OR_CHANGED"
            elif action in {"NAO_EXISTE_NA_BASE", "REJEITAR_CANDIDATO"} and decision["import_id"] != base_id:
                stale = "STALE_BASE_VERSION"
            if stale:
                state = "invalidated"
                effective.update(
                    match_type="REVISAR", scanner_key=None, scanner_status=None, confidence=None, requires_review=True
                )
                effective["reasons"] = [stale + ": nova decisão ou reavaliação necessária."]
            elif action in {"CONFIRMAR_MATCH", "NAO_EXISTE_NA_BASE"}:
                state = (
                    "resolved"
                    if decision["review_item_id"] == item["id"] and decision["run_id"] == item["run_id"]
                    else "reused"
                )
                effective.update(
                    match_type="EXATO_CONFIRMADO_HUMANAMENTE" if target else "CONFIRMADO_AUSENTE_NA_BASE",
                    scanner_key=target.key if target else None,
                    scanner_status=target.status if target else None,
                    confidence=None,
                    requires_review=False,
                )
                effective["reasons"] = [f"Decisão humana {decision['id']}; identidade não altera suporte."]
            elif action == "REJEITAR_CANDIDATO":
                rejected = set()
                for previous in reversed(decisions):
                    if previous["action"] != "REJEITAR_CANDIDATO" or previous["import_id"] != base_id:
                        break
                    rejected.add(previous["candidate_key"])
                effective["candidates"] = [c for c in effective["candidates"] if c["scanner_key"] not in rejected]
                effective["candidates_total"] = len(effective["candidates"])
                effective.update(
                    match_type="REVISAR", scanner_key=None, scanner_status=None, confidence=None, requires_review=True
                )
                effective["reasons"] = [
                    "Candidatos rejeitados: "
                    + ", ".join(sorted(rejected))
                    + "; não promove alternativa automaticamente."
                ]
            else:
                state = "ignored" if action == "IGNORAR" else "deferred"
        elif run_base != base_id:
            state = "invalidated"
        elif not needs_attention(effective, load_policy()):
            state = "resolved"
        if not item["active"] or self.observation(item)[1] != item["signature"]:
            state = "invalidated"
            stale = "ADVERTISEMENT_IDENTITY_CHANGED"
            effective.update(
                match_type="REVISAR", scanner_key=None, scanner_status=None, confidence=None, requires_review=True
            )
            effective["reasons"] = ["Identidade alterada; consulte o item ativo do anúncio."]
        return effective, state, decision, stale

    def _refresh(self, item_id, base_id, base):
        item = self._item(item_id)
        effective, state, decision, stale = self._evaluate(item, base_id, base)
        did = decision["id"] if decision else None
        if stale and (
            item["state"] != state or item["evaluated_import_id"] != base_id or item["applied_decision_id"] != did
        ):
            self._event(item_id, base_id, did, stale)
        self.connection.execute(
            "UPDATE review_items SET effective_json=?,state=?,priority=?,applied_decision_id=?,evaluated_import_id=?,updated_at=? WHERE id=?",
            (encode(effective), state, priority(effective, state, load_policy()), did, base_id, now(), item_id),
        )
        item = self._item(item_id)
        item["human_decision"] = decision
        item["memory"] = {
            "decision_id": did,
            "source_item_id": decision["review_item_id"] if decision else None,
            "source_import_id": decision["import_id"] if decision else None,
            "source_run_id": decision["run_id"] if decision else None,
            "scope": json.loads(decision["policy_json"]).get("memory_scope") if decision else None,
            "valid": bool(decision and not stale and item["active"]),
            "reused": bool(
                decision
                and decision["action"] in SHARED_ACTIONS
                and not stale
                and item["active"]
                and (decision["review_item_id"] != item_id or decision["run_id"] != item["run_id"])
            ),
            "stale_reason": stale,
        }
        return item

    def sync(self, collection_id, entries):
        """One atomic queue projection of a matching batch; repeated runs do not duplicate occurrences."""
        results = []
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            base_id, _, motos = self.matching_snapshot()
            base = {m.key: m for m in motos}
            policy = load_policy()
            for ad, run_id in entries:
                run = self.get_match(run_id)
                if run["import_id"] != base_id:
                    raise ValueError("Base mudou durante o matching; execute novamente")
                source = self.connection.execute(
                    "SELECT payload_json FROM partner_observations WHERE collection_id=? AND partner=? AND external_id=?",
                    (collection_id, ad["partner"], ad["external_id"]),
                ).fetchone()
                # Cached collections carry their own ads inside summary_json, without new observations.
                if source is None:
                    row = self.connection.execute(
                        "SELECT summary_json FROM partner_collections WHERE id=?", (collection_id,)
                    ).fetchone()
                    cached = json.loads(row[0]) if row else {}
                    source_ad = next(
                        (
                            asdict(PartnerMotorcycle(**a))
                            for a in cached.get("advertisements", [])
                            if a["external_id"] == ad["external_id"] and a["partner"] == ad["partner"]
                        ),
                        None,
                    )
                else:
                    source_ad = asdict(PartnerMotorcycle(**json.loads(source[0])))
                if source_ad != ad:
                    raise ValueError("Anúncio não corresponde à observação persistida")
                query = run["automatic_result"]["query"]
                if query != {
                    "manufacturer": ad["manufacturer"] or "",
                    "model": ad["model"] or "",
                    "version": ad["version"] or "",
                    "year": ad["year"],
                }:
                    raise ValueError("Matching não corresponde ao anúncio")
                sig = signature(ad)
                existing = self.connection.execute(
                    "SELECT id,signature,collection_id FROM review_items WHERE partner=? AND external_id=? AND active=1",
                    (ad["partner"], ad["external_id"]),
                ).fetchone()
                if existing and collection_id < existing[2]:
                    raise ValueError("Coleta anterior à fila atual; use relatório histórico já salvo")
                if existing and existing[1] != sig:
                    self.connection.execute(
                        "UPDATE review_items SET active=0,state='invalidated',updated_at=? WHERE id=?",
                        (now(), existing[0]),
                    )
                    self._event(existing[0], base_id, None, "ADVERTISEMENT_IDENTITY_CHANGED")
                memory = self.connection.execute(
                    "SELECT 1 FROM review_decisions WHERE signature=? AND action IN ('CONFIRMAR_MATCH','REJEITAR_CANDIDATO','NAO_EXISTE_NA_BASE') LIMIT 1",
                    (sig,),
                ).fetchone()
                automatic = run["automatic_result"]
                if not existing and not memory and not needs_attention(automatic, policy):
                    results.append(None)
                    continue
                timestamp = now()
                self.connection.execute(
                    "INSERT INTO review_items(partner,external_id,signature,identity_json,created_at,updated_at,last_seen,state,priority,collection_id,run_id,evaluated_import_id,advertisement_json,automatic_json,effective_json) "
                    "VALUES (?,?,?,?,?,?,?,'pending','medium',?,?,?,?,?,?) ON CONFLICT(partner,external_id,signature) DO UPDATE SET "
                    "active=1,updated_at=excluded.updated_at,last_seen=MAX(review_items.last_seen,excluded.last_seen),collection_id=excluded.collection_id,run_id=excluded.run_id,advertisement_json=excluded.advertisement_json,automatic_json=excluded.automatic_json",
                    (
                        ad["partner"],
                        ad["external_id"],
                        sig,
                        encode(identity(ad)),
                        timestamp,
                        timestamp,
                        ad["collected_at"],
                        collection_id,
                        run_id,
                        base_id,
                        encode(ad),
                        encode(automatic),
                        encode(automatic),
                    ),
                )
                item_id = self.connection.execute(
                    "SELECT id FROM review_items WHERE partner=? AND external_id=? AND signature=?",
                    (ad["partner"], ad["external_id"], sig),
                ).fetchone()[0]
                self.connection.execute(
                    "INSERT OR IGNORE INTO review_occurrences(review_item_id,collection_id,run_id,import_id,policy_json,advertisement_json,automatic_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        item_id,
                        collection_id,
                        run_id,
                        base_id,
                        encode(run["policy"]),
                        encode(ad),
                        encode(automatic),
                        timestamp,
                    ),
                )
                results.append(self._refresh(item_id, base_id, base))
        return results

    def show(self, item_id):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            base_id, _, motos = self.matching_snapshot()
            item = self._refresh(item_id, base_id, {m.key: m for m in motos})
            item["history"] = self._decisions(item)
            cursor = self.connection.execute(
                "SELECT * FROM review_events WHERE review_item_id=? ORDER BY id", (item_id,)
            )
            item["events"] = [dict(zip((c[0] for c in cursor.description), row)) for row in cursor.fetchall()]
            item["occurrences"] = self.connection.execute(
                "SELECT COUNT(*) FROM review_occurrences WHERE review_item_id=?", (item_id,)
            ).fetchone()[0]
        return item

    def list_items(self, status=None, requested_priority=None, include_inactive=False):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            base_id, _, motos = self.matching_snapshot()
            base = {m.key: m for m in motos}
            ids = self.connection.execute(
                "SELECT id FROM review_items WHERE active=1 OR ? ORDER BY id", (int(include_inactive),)
            ).fetchall()
            items = [self._refresh(row[0], base_id, base) for row in ids]
        return [
            i
            for i in items
            if (status is None or i["state"] == status)
            and (requested_priority is None or i["priority"] == requested_priority)
        ]

    def observation(self, item):
        row = self.connection.execute(
            "SELECT latest_collection_id,json_object('partner',partner,'manufacturer',json_extract(payload_json,'$.manufacturer'),"
            "'model',json_extract(payload_json,'$.model'),'version',json_extract(payload_json,'$.version'),'year',json_extract(payload_json,'$.year')) "
            "FROM partner_advertisements WHERE partner=? AND external_id=?",
            (item["partner"], item["external_id"]),
        ).fetchone()
        return (row[0], signature(json.loads(row[1]))) if row else (None, item["signature"])

    def revision(self, item, base_id):
        decisions = self._decisions(item)
        observed = self.observation(item)
        value = [
            item["id"],
            item["signature"],
            item["run_id"],
            item["active"],
            base_id,
            decisions[-1]["id"] if decisions else None,
            observed[0] if observed else None,
        ]
        return hashlib.sha256(encode(value).encode()).hexdigest()

    def decide(
        self, item_id, action, reviewer, note, candidate_key=None, *, submission_id=None, expected_revision=None
    ):
        if action not in ACTIONS or not reviewer.strip() or not note.strip():
            raise ValueError("Ação, reviewer e justificativa são obrigatórios")
        if (action in {"CONFIRMAR_MATCH", "REJEITAR_CANDIDATO"}) != bool(candidate_key):
            raise ValueError("Candidato obrigatório somente para confirmar/rejeitar")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            request = encode([item_id, action, reviewer.strip(), note.strip(), candidate_key, expected_revision])
            if submission_id:
                saved = self.connection.execute(
                    "SELECT request_json,decision_id FROM review_submissions WHERE request_id=?", (submission_id,)
                ).fetchone()
                if saved:
                    if saved[0] != request:
                        raise ValueError("Identificador de submissão já usado com outros dados")
                    return {"id": item_id, "decision_id": saved[1], "submission_replayed": True}
            base_id, _, motos = self.matching_snapshot()
            base = {m.key: m for m in motos}
            item = self._item(item_id)
            if expected_revision is not None and expected_revision != self.revision(item, base_id):
                raise ValueError("Item ou base mudou desde a abertura. Atualize e confira os dados antes de decidir.")
            before_state = self._evaluate(item, base_id, base)[1]
            if not item["active"]:
                raise ValueError("Anúncio mudou de identidade; revise o item ativo")
            if self.observation(item)[1] != item["signature"]:
                raise ValueError("A identidade coletada mudou. Gere a cobertura da nova coleta antes de revisar.")
            if action in SHARED_ACTIONS and not complete_identity(item["identity"]):
                raise ValueError("Identidade incompleta; mantenha pendente até corrigir na origem")
            target = base.get(candidate_key)
            if candidate_key and target is None:
                raise ValueError("Candidato não existe na base atual")
            if target:
                # Human may resolve naming/trim uncertainty, never silently cross brand/year.
                aliases = self.get_match(item["run_id"])["policy"]["manufacturer_aliases"]
                brand = aliases.get(item["identity"]["manufacturer"], item["identity"]["manufacturer"])
                if target.year != item["identity"]["year"] or target.manufacturer != brand:
                    raise ValueError("Candidato possui fabricante ou ano incompatível")
            previous = self._decisions(item)
            run = self.get_match(item["run_id"])
            policy = {
                "operational_version": "3.2",
                "review_policy": load_policy(),
                "matching_policy": run["policy"],
                "source_run_import_id": run["import_id"],
                "memory_scope": memory_scope(action, run["automatic_result"], run["policy"], target),
            }
            cursor = self.connection.execute(
                "INSERT INTO review_decisions(review_item_id,signature,action,reviewer,note,created_at,candidate_key,target_identity_json,import_id,run_id,policy_json,identity_json,previous_decision_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item_id,
                    item["signature"],
                    action,
                    reviewer.strip(),
                    note.strip(),
                    now(),
                    candidate_key,
                    encode(target_identity(target)) if target else None,
                    base_id,
                    item["run_id"],
                    encode(policy),
                    encode(item["identity"]),
                    previous[-1]["id"] if previous else None,
                ),
            )
            decision_id = cursor.lastrowid
            # All existing equivalent items observe the same newest human event atomically.
            ids = self.connection.execute(
                "SELECT id FROM review_items WHERE signature=? AND active=1", (item["signature"],)
            ).fetchall()
            for (current_id,) in ids:
                self._refresh(current_id, base_id, base)
            self.connection.execute(
                "INSERT INTO review_decision_transitions VALUES (?,?,?)",
                (decision_id, before_state, self._item(item_id)["state"]),
            )
            if submission_id:
                self.connection.execute(
                    "INSERT INTO review_submissions VALUES (?,?,?)", (submission_id, request, decision_id)
                )
        return self.show(item_id)
