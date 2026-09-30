"""Explicit refresh/simulation and audited human priority, independent of matching."""

import json
import logging
import time
from collections import Counter
from datetime import datetime

from database.prioritization_repository import (
    PrioritizationRepository,
    assessment_history,
    assessments,
    digest,
    installed,
    operational_sources,
    override_history,
    reading,
    source_token,
)
from database.transaction import atomic_database
from partners.registry import PartnerRegistry
from services.prioritization_engine import assess
from services.prioritization_policy import load_policy, policy_hash, validate_policy
from services.scheduler_config import utcnow

LOGGER = logging.getLogger(__name__)


def elapsed(stamp, now):
    try:
        return max(0, (now - datetime.fromisoformat(stamp)).total_seconds() / 3600)
    except (ValueError, TypeError):
        return float("inf")


class PrioritizationService:
    def __init__(self, config, policy=None, clock=utcnow, registry=None):
        self.config = config
        self.policy = validate_policy(policy) if policy is not None else load_policy()
        self.clock = clock
        self.registry = registry or PartnerRegistry()
        self.registry.get(config.partner)

    def refresh(self, origin="manual"):
        if self.config.read_only:
            raise ValueError("Modo somente leitura: reavaliação desabilitada")
        if not self.policy["enabled"]:
            return {"disabled": True, "evaluated": 0, "changed": 0}
        start = time.perf_counter()
        now = self.clock()
        partner = self.config.partner
        # Acquire SQLite's writer transaction before reading evidence, avoiding mixed publication snapshots.
        with atomic_database(self.config.database), PrioritizationRepository(self.config.database) as repo:
            sources = operational_sources(self.config.database, partner)
            prior_state = repo.connection.execute(
                "SELECT checked_at FROM priority_maintenance WHERE partner=?", (partner,)
            ).fetchone()
            outdated = bool(prior_state and elapsed(prior_state[0], now) >= self.policy["stale_after_hours"])
            token = source_token(repo.connection, partner)
            repo.connection.execute("UPDATE priority_cases SET active=0 WHERE partner=?", (partner,))
            counts = Counter()
            changed = 0
            retained = 0
            previous_sources = {}
            if origin == "scanner_publication":
                previous_sources = {
                    (r[1], r[2]): (r[0], json.loads(r[3]))
                    for r in repo.connection.execute(
                        "SELECT c.id,c.entity_id,c.identity_key,a.payload_json FROM priority_cases c JOIN priority_assessments a ON a.id=c.latest_assessment_id WHERE c.partner=?",
                        (partner,),
                    )
                }

            for source in sources:
                prior = previous_sources.get((source["entity_id"], source["identity_key"]))
                if prior and prior[1].get("policy_hash") == policy_hash(self.policy):
                    old_evidence = {
                        k: v for k, v in prior[1].get("evidence", {}).items() if k != "scanner_base_version"
                    }
                    new_evidence = {k: v for k, v in source.items() if k != "scanner_base_version"}
                    if old_evidence == new_evidence:
                        repo.connection.execute("UPDATE priority_cases SET active=1 WHERE id=?", (prior[0],))
                        retained += 1
                        counts[prior[1]["suggested_priority"]] += 1
                        continue
                result = assess(source, self.policy, now)
                case_id, assessment_id, updated, previous = repo.save(partner, source, result, origin)
                changed += updated
                counts[result["suggested_priority"]] += 1
                if self.policy["alerts_enabled"] and not source.get("development"):
                    if outdated and previous and previous["suggested_priority"] == "high":
                        repo.notify(
                            case_id,
                            assessment_id,
                            "PRIORITY_OUTDATED",
                            f"outdated:{case_id}:{digest(previous)}",
                            "Avaliação de alta prioridade ultrapassou o prazo de atualização",
                            now.isoformat(),
                        )
                    if result["suggested_priority"] == "high" and (
                        not previous or previous["suggested_priority"] != "high"
                    ):
                        repo.notify(
                            case_id,
                            assessment_id,
                            "PRIORITY_HIGH",
                            f"high:{case_id}:{assessment_id}",
                            "Caso passou para prioridade sugerida alta",
                            now.isoformat(),
                        )
                    if (
                        result["suggested_priority"] == "high"
                        and result["awaiting_human"]
                        and (result["pending_days"] or 0) >= self.policy["high_pending_days"]
                    ):
                        # One notice per pending episode, not per recalculation/day.
                        repo.notify(
                            case_id,
                            assessment_id,
                            "PRIORITY_PENDING",
                            f"pending:{case_id}:{source.get('pending_since')}",
                            "Caso de prioridade alta aguarda decisão humana",
                            now.isoformat(),
                        )
            repo.connection.execute(
                "INSERT INTO priority_maintenance VALUES (?,?,?,?) ON CONFLICT(partner) DO UPDATE SET checked_at=excluded.checked_at,source_token=excluded.source_token,policy_hash=excluded.policy_hash",
                (
                    partner,
                    prior_state[0] if retained and prior_state else now.isoformat(),
                    token,
                    policy_hash(self.policy),
                ),
            )
        return {
            "evaluated": len(sources) - retained,
            "retained": retained,
            "changed": changed,
            "by_priority": dict(counts),
            "seconds": round(time.perf_counter() - start, 4),
        }

    def listing(self, filters=None, text="", sort="score_desc", page=0, size=8, start=None, end=None):
        if type(page) is not int or page < 0 or type(size) is not int or not 1 <= size <= 50:
            raise ValueError("Paginação inválida")
        rows, maintenance, token = assessments(self.config.database, self.config.partner)
        stale = bool(
            maintenance
            and (
                token != maintenance["source_token"]
                or maintenance["policy_hash"] != policy_hash(self.policy)
                or elapsed(maintenance["checked_at"], self.clock()) >= self.policy["stale_after_hours"]
            )
        )
        for row in rows:
            evidence = row["evidence"]
            row.update(
                {
                    k: evidence.get(k)
                    for k in (
                        "manufacturer",
                        "model",
                        "version",
                        "year",
                        "human_status",
                        "base_status",
                        "source_url",
                        "review_item_id",
                        "primary_image_url",
                        "first_seen",
                        "last_seen",
                    )
                }
            )
            row["assigned_to"] = (evidence.get("development") or {}).get("assigned_to", "")
            row["has_development"] = bool(evidence.get("development"))
            row["manual_override"] = row["manual_priority"] is not None
            row["stale"] = stale
        metrics = dict(Counter(r["suggested_priority"] for r in rows))
        metrics.update(
            total=len(rows),
            awaiting_human=sum(r["awaiting_human"] for r in rows),
            manual=sum(r["manual_override"] for r in rows),
            development=sum(r["has_development"] for r in rows),
        )
        facets = {
            key: sorted({r.get(key) for r in rows if r.get(key) is not None}, key=str)
            for key in (
                "manufacturer",
                "model",
                "year",
                "partner",
                "base_status",
                "human_status",
                "suggested_priority",
                "effective_priority",
                "assigned_to",
                "has_development",
            )
        }
        facets["partner"] = [p.partner_key for p in self.registry.list() if p.partner_key == self.config.partner]
        for key, values in (filters or {}).items():
            if key == "photo":
                if values:
                    rows = [r for r in rows if bool(r.get("primary_image_url")) == (values[0] == "with")]
            elif key in facets:
                if values:
                    rows = [r for r in rows if r.get(key) in values]
            else:
                raise ValueError("Filtro inválido")
        terms = text.casefold().split()
        rows = [
            r
            for r in rows
            if all(
                t
                in (
                    str(r.get("manufacturer"))
                    + " "
                    + str(r.get("model"))
                    + " "
                    + str(r.get("year"))
                    + " "
                    + r["entity_id"]
                    + " "
                    + r.get("assigned_to", "")
                ).casefold()
                for t in terms
            )
            and (not start or r["calculated_at"][:10] >= str(start))
            and (not end or r["calculated_at"][:10] <= str(end))
        ]
        orders = {
            "score_desc": lambda r: (r["score"] is None, -(r["score"] or 0)),
            "score_asc": lambda r: (r["score"] is None, r["score"] or 0),
            "pending": lambda r: -(r["pending_days"] or 0),
            "recent": lambda r: -datetime.fromisoformat(r["calculated_at"]).timestamp(),
            "model": lambda r: (r.get("manufacturer") or "", r.get("model") or ""),
            "effective": lambda r: (
                {"high": 0, "medium": 1, "low": 2}.get(r["effective_priority"], 3),
                not r["manual_override"],
            ),
        }
        if sort not in orders:
            raise ValueError("Ordenação inválida")
        rows.sort(key=lambda r: (orders[sort](r), r["id"]))
        return {
            "items": rows[page * size : (page + 1) * size],
            "total": len(rows),
            "metrics": metrics,
            "facets": facets,
            "stale": stale,
            "installed": maintenance is not None,
            "enabled": self.policy["enabled"],
        }

    def detail(self, case_id, page=0):
        rows, _, _ = assessments(self.config.database, self.config.partner)
        item = next((r for r in rows if r["id"] == case_id), None)
        if not item:
            raise ValueError("Avaliação não encontrada para este parceiro")
        item["history"] = assessment_history(self.config.database, case_id, self.config.partner, page)
        item["overrides"] = override_history(self.config.database, case_id, self.config.partner)
        return item

    def override(self, case_id, priority, *, author, reason, request_key, revision):
        if self.config.read_only:
            raise ValueError("Modo somente leitura: alterações desabilitadas")
        if not self.policy["enabled"] or not self.policy["allow_manual_override"]:
            raise ValueError("Alteração manual desabilitada")
        if priority not in {None, "high", "medium", "low"}:
            raise ValueError("Prioridade inválida")
        if (
            not isinstance(author, str)
            or not author.strip()
            or len(author) > 120
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 4000
        ):
            raise ValueError("Informe responsável e justificativa válidos")
        if not isinstance(request_key, str) or not request_key or len(request_key) > 200:
            raise ValueError("Solicitação inválida")
        payload = digest([case_id, self.config.partner, priority, author, reason, revision])
        with atomic_database(self.config.database), PrioritizationRepository(self.config.database) as repo:
            prior = repo.connection.execute(
                "SELECT case_id,request_hash FROM priority_overrides WHERE request_key=?", (request_key,)
            ).fetchone()
            if prior:
                if prior[1] != payload:
                    raise ValueError("Solicitação já usada com outros dados")
                return prior[0]
            state = repo.connection.execute(
                "SELECT source_token,policy_hash FROM priority_maintenance WHERE partner=?", (self.config.partner,)
            ).fetchone()
            if (
                not state
                or state[0] != source_token(repo.connection, self.config.partner)
                or state[1] != policy_hash(self.policy)
            ):
                raise ValueError("Dados ou política alterados; reavalie antes de salvar")
            row = repo.connection.execute(
                "SELECT manual_priority,revision FROM priority_cases WHERE id=? AND partner=? AND active=1",
                (case_id, self.config.partner),
            ).fetchone()
            if not row or type(revision) is not int or row[1] != revision:
                raise ValueError("Avaliação alterada; atualize antes de salvar")
            stamp = self.clock().isoformat()
            repo.connection.execute(
                "INSERT INTO priority_overrides(case_id,created_at,author,reason,before_priority,after_priority,request_key,request_hash) VALUES (?,?,?,?,?,?,?,?)",
                (case_id, stamp, author.strip(), reason.strip(), row[0], priority, request_key, payload),
            )
            repo.connection.execute(
                "UPDATE priority_cases SET manual_priority=?,override_reason=?,override_author=?,override_at=?,revision=revision+1 WHERE id=?",
                (priority, reason.strip(), author.strip(), stamp, case_id),
            )
        return case_id

    def simulate(self, policy):
        policy = validate_policy(policy)
        sources = operational_sources(self.config.database, self.config.partner)
        now = self.clock()
        changes = []
        for source in sources:
            before, after = assess(source, self.policy, now), assess(source, policy, now)
            changes.append(
                {
                    "entity_id": source["entity_id"],
                    "before": before["score"],
                    "after": after["score"],
                    "from": before["suggested_priority"],
                    "to": after["suggested_priority"],
                }
            )
        return {"evaluated": len(changes), "changed_band": sum(r["from"] != r["to"] for r in changes), "items": changes}


def safe_refresh(database, partner=None, origin="scheduled"):
    """Activated partners only. Source commands succeed even if this derived projection fails."""
    from services.dashboard_service import DashboardConfig

    try:
        policy = load_policy()
        if not policy["enabled"]:
            return
        with reading(database) as db:
            if not installed(db):
                return
            active = {r[0]: dict(r) for r in db.execute("SELECT * FROM priority_maintenance")}
        registry = PartnerRegistry()
        for entry in registry.list(enabled_only=True):
            key = entry.partner_key
            if key not in active or (partner and key != partner):
                continue
            with reading(database) as db:
                token = source_token(db, key)
            state = active[key]
            now = utcnow()
            if (
                token != state["source_token"]
                or policy_hash(policy) != state["policy_hash"]
                or elapsed(state["checked_at"], now) >= policy["reassess_hours"]
            ):
                PrioritizationService(DashboardConfig(database, key), policy).refresh(origin)
    except Exception:
        LOGGER.exception("Reavaliação indisponível; dados operacionais preservados")
