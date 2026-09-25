"""Detect operational events from committed evidence, with durable delivery retries."""

import hashlib
import json
import logging
from collections import Counter
from dataclasses import asdict

from database.alert_repository import AlertRepository, read_alert_history, read_alerts
from database.repository import encode
from database.transaction import atomic_database
from matching.matcher import Matcher
from matching.models import MotorcycleQuery
from matching.review_policy import load_policy, priority
from matching.rules import load_matching_rules
from scanner_base.models import Motorcycle
from services.alert_config import load_alert_config
from services.refinement_service import diagnostics, probable_absence
from services.scheduler_config import utcnow

LOGGER = logging.getLogger("services.pipeline_service")
TITLES = {
    "NOVO_ANUNCIO": "Novo anúncio no parceiro",
    "POSSIVEL_NOVA_MOTO": "Possível nova moto fora da base",
    "SEM_SUPORTE": "Moto com sistemas sem suporte",
    "SUPORTE_PARCIAL": "Moto com suporte parcial",
    "REVISAO_ALTA_PRIORIDADE": "Novo caso de alta prioridade para revisão",
    "DECISAO_DESATUALIZADA": "A decisão anterior precisa ser revisada",
    "FALHA_COLETA": "Falha na coleta do catálogo",
    "FALHA_PIPELINE": "Falha na atualização automática",
    "COLETA_PARCIAL": "Coleta incompleta ou atualização com avisos",
    "NOVA_VERSAO_BASE": "Nova versão da base identificada",
}


def enqueue(repo, run_id, context):
    # Called in the same transaction as the terminal pipeline state.
    repo.connection.execute(
        "INSERT OR IGNORE INTO alert_deliveries(pipeline_run_id,context_json) VALUES (?,?)", (run_id, encode(context))
    )


def event(kind, identity, details, *, severity="ALTA", ad=None, result=None, review_id=None):
    ad, result = ad or {}, result or {}
    return {
        "alert_type": kind,
        "severity": severity,
        "partner": "wr_motos",
        "external_id": ad.get("external_id"),
        "manufacturer": ad.get("manufacturer"),
        "scanner_key": result.get("scanner_key"),
        "review_item_id": review_id,
        "deduplication_key": hashlib.sha256(encode([kind, "wr_motos", identity]).encode()).hexdigest(),
        "title": TITLES[kind],
        "message": "Hipótese sobre a base consultada; não confirma ausência nem falta de suporte."
        if kind == "POSSIVEL_NOVA_MOTO"
        else TITLES[kind] + ". Consulte os detalhes e a origem registrada.",
        "details": details,
    }


def detect(repo, run, context, config):
    summary = json.loads(run["summary_json"])
    events, condition_types = [], []
    success = run["status"] in {"SUCCESS", "PARTIAL_SUCCESS"}
    failures = [
        dict(zip(("id", "status", "stage"), r))
        for r in repo.connection.execute(
            "SELECT p.id,p.status,json_extract(d.context_json,'$.stage') FROM pipeline_runs p LEFT JOIN alert_deliveries d ON d.pipeline_run_id=p.id WHERE p.id<=? AND p.status IN ('SUCCESS','PARTIAL_SUCCESS','FAILED') ORDER BY p.id DESC",
            (run["id"],),
        )
    ]
    streak = 0
    for previous in failures:
        if previous["status"] != "FAILED":
            break
        streak += 1
    collection_streak = 0
    for previous in failures:
        if previous["status"] != "FAILED" or previous["stage"] != "collection":
            break
        collection_streak += 1
    if config.failure_enabled:
        condition_types += ["FALHA_COLETA", "FALHA_PIPELINE"] if success else []
        if context.get("stage") == "publication" and not success:
            condition_types.append("FALHA_COLETA")
        if run["status"] == "FAILED":
            severity = (
                "CRITICA"
                if streak >= config.failure_critical_after
                else "ALTA"
                if streak >= config.failure_high_after
                else "ATENCAO"
            )
            details = {
                "stage": context.get("stage"),
                "attempts": summary.get("attempts"),
                "consecutive_failures": streak,
                "error_codes": [e.get("code") for e in summary.get("errors", [])],
                "next_run_at": context.get("next_run_at"),
                "date": run["finished_at"],
                "error": "A coleta não foi concluída; dados anteriores preservados."
                if context.get("stage") == "collection"
                else "Não foi possível publicar a atualização; dados anteriores preservados.",
            }
            events.append(event("FALHA_PIPELINE", "pipeline", details, severity=severity))
            if context.get("stage") == "collection":
                collection_severity = (
                    "CRITICA"
                    if collection_streak >= config.failure_critical_after
                    else "ALTA"
                    if collection_streak >= config.failure_high_after
                    else "ATENCAO"
                )
                events.append(
                    event(
                        "FALHA_COLETA",
                        "collection",
                        {**details, "consecutive_failures": collection_streak},
                        severity=collection_severity,
                    )
                )
    if config.partial_collection_enabled:
        if success:
            condition_types.append("COLETA_PARCIAL")
        if run["status"] == "PARTIAL_SUCCESS" or context.get("partial"):
            events.append(
                event(
                    "COLETA_PARCIAL",
                    "collection",
                    {
                        "warnings": summary.get("warnings", {}),
                        "incomplete": bool(context.get("partial")),
                        "published": success,
                    },
                    severity="ATENCAO",
                )
            )
    if not success:
        return events, condition_types
    report = json.loads(
        repo.connection.execute(
            "SELECT report_json FROM coverage_runs WHERE id=?", (context["coverage_id"],)
        ).fetchone()[0]
    )
    base_id = report["import_id"]
    motos = [
        Motorcycle(**json.loads(r[0]))
        for r in repo.connection.execute("SELECT payload_json FROM motorcycle_snapshots WHERE import_id=?", (base_id,))
    ]
    base = {m.key: m for m in motos}
    policy = json.loads(repo.connection.execute("SELECT policy_json FROM imports WHERE id=?", (base_id,)).fetchone()[0])
    engine = Matcher(motos, policy["manufacturer_aliases"], load_matching_rules())
    enabled_conditions = {
        "POSSIVEL_NOVA_MOTO": config.probable_missing_enabled,
        "SEM_SUPORTE": config.unsupported_enabled,
        "SUPORTE_PARCIAL": config.partial_support_enabled,
    }
    condition_types += [k for k, enabled in enabled_conditions.items() if enabled]
    new_ids = set(context.get("new_ids", []))
    for group in report["groups"].values():
        for item in group:
            ad, result = item["advertisement"], item["effective_result"]
            rid = item.get("review_item_id")
            clean_ad = {k: v for k, v in ad.items() if k not in {"raw_data", "raw_text"}}
            target = base.get(result.get("scanner_key"))
            details = {
                "advertisement": clean_ad,
                "matching": result["match_type"],
                "coverage": result.get("scanner_status"),
                "base_id": base_id,
                "systems": {
                    k: getattr(target, k)
                    for k in ("supported_systems", "unsupported_systems", "analysis_systems", "unknown_systems")
                }
                if target
                else {},
            }
            new = ad["external_id"] in new_ids
            identity = [ad["external_id"], base_id]
            if new and config.new_ad_enabled:
                events.append(
                    event(
                        "NOVO_ANUNCIO",
                        ad["external_id"],
                        details,
                        severity="INFO"
                        if result.get("scanner_status") == "SUPORTADO" and not result["requires_review"]
                        else "ATENCAO",
                        ad=ad,
                        result=result,
                        review_id=rid,
                    )
                )
            interpreted = bool(
                ad.get("manufacturer")
                and ad.get("model")
                and ad.get("year")
                and not (set(ad.get("parse_warnings", [])) - {"FILTROS_ZERO_KM_CONFLITANTES"})
            )
            if config.probable_missing_enabled and interpreted and result["match_type"] == "NAO_ENCONTRADA_NA_BASE":
                reason = probable_absence(
                    ad,
                    result,
                    diagnostics(
                        MotorcycleQuery(ad["manufacturer"], ad["model"], ad["year"], ad.get("version") or ""), engine
                    ),
                )
                # A new, well-parsed unmatched ad or the existing conservative absence rule.
                key = event("POSSIVEL_NOVA_MOTO", identity, details)["deduplication_key"]
                existing = repo.connection.execute("SELECT 1 FROM alerts WHERE deduplication_key=?", (key,)).fetchone()
                if new or reason or existing:
                    events.append(
                        event(
                            "POSSIVEL_NOVA_MOTO",
                            identity,
                            {
                                **details,
                                "evidence": reason
                                or "Anúncio novo com identidade interpretada, sem correspondência na base.",
                            },
                            ad=ad,
                            result=result,
                            review_id=rid,
                        )
                    )
            status = result.get("scanner_status")
            if (
                target
                and not result["requires_review"]
                and status in {"SEM_SUPORTE", "SUPORTE_PARCIAL"}
                and enabled_conditions[status]
            ):
                events.append(event(status, identity, details, ad=ad, result=result, review_id=rid))
            if (
                config.high_priority_review_enabled
                and rid
                and rid > context.get("review_max_before", 0)
                and priority(result, item.get("review_state") or "pending", load_policy()) == "high"
            ):
                events.append(event("REVISAO_ALTA_PRIORIDADE", rid, details, ad=ad, result=result, review_id=rid))
    if config.stale_decision_enabled:
        for row in repo.connection.execute(
            "SELECT e.decision_id,e.import_id,e.reason,e.review_item_id,d.import_id,d.action,d.candidate_key FROM review_events e JOIN review_decisions d ON d.id=e.decision_id WHERE e.id<=? AND e.import_id=? AND e.reason LIKE 'STALE%'",
            (context.get("review_event_max", 0), base_id),
        ):
            decision_id, new_base, reason, rid, old_base, action, key = row
            events.append(
                event(
                    "DECISAO_DESATUALIZADA",
                    [decision_id, new_base],
                    {
                        "decision_id": decision_id,
                        "reason": reason,
                        "old_base_id": old_base,
                        "base_id": new_base,
                        "decision": action,
                        "scanner_key": key,
                    },
                    review_id=rid,
                )
            )
    if config.base_version_enabled and context.get("previous_base") and context["previous_base"] != base_id:
        events.append(
            event(
                "NOVA_VERSAO_BASE",
                base_id,
                {"old_base_id": context["previous_base"], "base_id": base_id},
                severity="INFO",
            )
        )
    return events, condition_types


def process_pending(database, config=None):
    config = config or load_alert_config()
    with AlertRepository(database) as repo:
        pending = [
            r[0]
            for r in repo.connection.execute(
                "SELECT pipeline_run_id FROM alert_deliveries WHERE processed_at IS NULL ORDER BY pipeline_run_id"
            )
        ]
    for run_id in pending:
        try:
            with atomic_database(database):
                with AlertRepository(database) as repo:
                    delivery = repo.connection.execute(
                        "SELECT context_json,processed_at FROM alert_deliveries WHERE pipeline_run_id=?", (run_id,)
                    ).fetchone()
                    if delivery[1]:
                        continue
                    cursor = repo.connection.execute("SELECT * FROM pipeline_runs WHERE id=?", (run_id,))
                    run = dict(zip((c[0] for c in cursor.description), cursor.fetchone()))
                    context = json.loads(delivery[0])
                    events, condition_types = detect(repo, run, context, config) if config.enabled else ([], [])
                    events = list({e["deduplication_key"]: e for e in events}.values())
                    counts = Counter()
                    keys = {e["deduplication_key"] for e in events}
                    repo.clear_conditions(condition_types, keys)
                    # Collapse duplicate stale events before counting, and dedup exact observations across runs.
                    for e in events:
                        kind = e["alert_type"]
                        token = (
                            str(run_id)
                            if kind in {"FALHA_COLETA", "FALHA_PIPELINE", "COLETA_PARCIAL"}
                            else encode([context.get("observation"), context.get("coverage_id")])
                        )
                        if kind in {
                            "NOVO_ANUNCIO",
                            "REVISAO_ALTA_PRIORIDADE",
                            "DECISAO_DESATUALIZADA",
                            "NOVA_VERSAO_BASE",
                        }:
                            token = e["deduplication_key"]
                        counts[repo.observe(e, run, token)] += 1
                    summary = json.loads(run["summary_json"])
                    summary["alerts"] = {
                        "policy": asdict(config),
                        "created": counts["created"],
                        "updated": counts["updated"],
                        "unchanged": counts["unchanged"],
                        "disabled": not config.enabled,
                        "by_type": dict(Counter(e["alert_type"] for e in events)),
                        "by_severity": dict(Counter(e["severity"] for e in events)),
                    }
                    summary.pop("alert_error", None)
                    repo.connection.execute(
                        "UPDATE pipeline_runs SET summary_json=? WHERE id=?", (encode(summary), run_id)
                    )
                    repo.connection.execute(
                        "UPDATE alert_deliveries SET processed_at=?,attempts=attempts+1,error_summary=NULL WHERE pipeline_run_id=?",
                        (utcnow().isoformat(), run_id),
                    )
        except Exception:
            LOGGER.exception("Falha na geração de alertas; execução=%s; entrega preservada para nova tentativa", run_id)
            with AlertRepository(database) as repo, repo.connection:
                repo.connection.execute(
                    "UPDATE alert_deliveries SET attempts=attempts+1,error_summary=? WHERE pipeline_run_id=?",
                    ("Não foi possível gerar os alertas; nova tentativa pendente.", run_id),
                )
                repo.connection.execute(
                    "UPDATE pipeline_runs SET summary_json=json_set(summary_json,'$.alert_error',?) WHERE id=?",
                    ("Geração de alertas pendente; consulte o registro local.", run_id),
                )
            break  # Preserve event order; retry on the next pipeline or explicit CLI.


def safe_process(database):
    try:
        process_pending(database)
    except Exception:
        LOGGER.exception("Serviço de alertas indisponível; entregas pendentes preservadas")
        try:
            with AlertRepository(database) as repo, repo.connection:
                repo.connection.execute(
                    "UPDATE alert_deliveries SET error_summary=? WHERE processed_at IS NULL",
                    ("Configuração ou serviço de alertas indisponível.",),
                )
                repo.connection.execute(
                    "UPDATE pipeline_runs SET summary_json=json_set(summary_json,'$.alert_error',?) WHERE id IN (SELECT pipeline_run_id FROM alert_deliveries WHERE processed_at IS NULL)",
                    ("Geração de alertas pendente; consulte o registro local.",),
                )
        except Exception:
            LOGGER.exception("Não foi possível registrar a indisponibilidade dos alertas no banco")


def filter_alerts(rows, filters=None, start=None, end=None, read=None, sort="priority"):
    filters = filters or {}
    result = [
        r
        for r in rows
        if all(not values or r.get(k) in values for k, values in filters.items())
        and (not start or r["last_seen_at"][:10] >= str(start))
        and (not end or r["last_seen_at"][:10] <= str(end))
        and (read is None or (r["status"] != "NOVO") == read)
    ]
    if sort == "priority":
        result.sort(key=lambda r: r["last_seen_at"], reverse=True)
        result.sort(
            key=lambda r: ({"CRITICA": 0, "ALTA": 1, "ATENCAO": 2, "INFO": 3}[r["severity"]], r["status"] != "NOVO")
        )
    else:
        result.sort(
            key=lambda r: r["last_seen_at"] if sort in {"recent", "oldest"} else r["title"], reverse=sort == "recent"
        )
    return result


class AlertService:
    def __init__(self, config):
        self.config = config

    def snapshot(self):
        return read_alerts(self.config.database, self.config.partner)

    def history(self, alert_id):
        return read_alert_history(self.config.database, alert_id, self.config.partner)

    def transition(self, alert_id, target):
        if self.config.read_only:
            raise ValueError("Painel em modo somente leitura")
        if alert_id < 0:
            from database.development_alert_repository import transition_alert

            return transition_alert(self.config.database, alert_id, target, self.config.partner)
        with AlertRepository(self.config.database) as repo:
            repo.transition(alert_id, target, self.config.partner)
