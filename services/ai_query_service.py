"""Finite read capabilities; providers never receive these objects or choose methods."""

import json
import re
from datetime import datetime, timezone

from database.ai_repository import AIRepository
from database.alert_repository import read_alerts
from database.dashboard_repository import DashboardRepository
from database.development_repository import list_items
from scanner_base.normalizer import normalize_text
from services.ai_context_service import selected_period, vehicle_terms
from services.ai_guardrails import INSUFFICIENT, MISSING, redact
from services.dashboard_service import DashboardConfig
from services.development_policy import CLOSED, STATES
from services.management_metrics_service import DEFINITIONS, ZONE, ManagementMetricsService, bounds
from services.partner_service import partner_status
from services.prioritization_service import PrioritizationService
from ui.textos import value

ROUTES = {
    "SCANNER_LOOKUP": "Base do scanner",
    "APPLICATION_LOOKUP": "Base do scanner",
    "CABLE_LOOKUP": "Base do scanner",
    "REVIEW_LOOKUP": "Fila de revisão",
    "PARTNER_LOOKUP": "Parceiros",
    "DEVELOPMENT_LOOKUP": "Motos para desenvolvimento",
    "PRIORITIZATION_LOOKUP": "Priorização operacional",
    "MANAGEMENT_METRICS": "Indicadores gerenciais",
    "ALERT_LOOKUP": "Alertas",
    "BASE_VERSION_LOOKUP": "Atualização da base do scanner",
    "RECENT_CHANGES": "Histórico",
}


def shown(value_):
    if value_ is None or value_ == "" or value_ == [] or value_ == {}:
        return MISSING
    if isinstance(value_, (dict, list)):
        return redact(json.dumps(value_, ensure_ascii=False))
    return redact(value_)


def identity(row):
    return " ".join(str(row.get(k) or "") for k in ("manufacturer", "model", "version", "year")).strip()


class AIQueryService:
    def __init__(self, database, partner="wr_motos", clock=None):
        self._repository = AIRepository(database)
        self._config = DashboardConfig(database, partner, read_only=True)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def query(self, intent, question, state, limit):
        limit = min(50, max(1, limit))
        result = {"facts": [], "sources": [], "total": 0, "choices": [], "route": ROUTES.get(intent)}

        def fact(text, kind, identifier, base=None):
            source = {"type": kind, "id": identifier}
            if base is not None:
                source["base_id"] = base
            result["facts"].append({"id": f"f{len(result['facts']) + 1}", "text": redact(text), "source": source})
            if source not in result["sources"]:
                result["sources"].append(source)

        q = normalize_text(question)
        counts = self._repository.get_counts()
        current_base = counts["base_id"] if counts else None
        if state.get("selected_base_id") != current_base:
            state.update(selected_vehicle_id=None, selected_base_id=current_base, choices=[])
        count_question = bool(re.search(r"QUANT[OA]S?|TOTAL", q)) and intent in {
            "SCANNER_LOOKUP",
            "APPLICATION_LOOKUP",
            "BASE_VERSION_LOOKUP",
        }
        if count_question:
            if counts:
                for key, label in (
                    ("vehicles", "Veículos"),
                    ("applications", "Aplicações"),
                    ("systems", "Sistemas distintos"),
                ):
                    fact(f"{label} na base ativa {current_base}: {counts[key]}.", "scanner_base_version", current_base)
            else:
                result["message"] = INSUFFICIENT
        elif intent in {"SCANNER_LOOKUP", "APPLICATION_LOOKUP", "CABLE_LOOKUP"}:
            explicit = re.search(r"\b(?:VEICULO|ID)\s*#?\s*(\d+)", q)
            terms = vehicle_terms(question)
            identifier = int(explicit[1]) if explicit else state.get("selected_vehicle_id") if not terms else None
            if not terms and identifier is None:
                result["message"] = "Informe fabricante, modelo e ano, ou selecione um veículo."
                return result
            found = self._repository.search_scanner(terms, limit, identifier)
            result["total"] = found["total"]
            if found["total"] != 1:
                state["selected_vehicle_id"] = None
                result["choices"] = found["items"]
                state["choices"] = [r["id"] for r in found["items"]]
                result["message"] = (
                    "Encontrei mais de uma correspondência. Selecione um veículo." if found["total"] else INSUFFICIENT
                )
                for row in found["items"]:
                    fact(f"Veículo #{row['id']}: {identity(row)}.", "scanner_vehicle", row["id"], current_base)
                return result
            row = found["items"][0]
            state.update(selected_vehicle_id=row["id"], selected_base_id=current_base, choices=[])
            fact(
                f"Veículo #{row['id']}: {identity(row)}. Situação no scanner: {value(row['status'])}. "
                f"Aplicações registradas: {row['record_count']}; sistemas do veículo: {row['system_count']}.",
                "scanner_vehicle",
                row["id"],
                current_base,
            )
            if intent != "SCANNER_LOOKUP":
                applications = self._repository.get_vehicle_applications(row["id"], max(1, limit - 1))
                result["total"] = applications["total"]
                result["count_label"] = "aplicações"
                result["displayed"] = len(applications["items"])
                for application in applications["items"]:
                    attrs = application.get("application_attributes") or {}
                    text = (
                        f"Sistema: {shown(application['system'])}; cabo: {shown(application['cable'])}; "
                        f"local do cabo: {shown(application['cable_location'])}; suporte: {value(application['status'])}."
                    )
                    for key, label in (
                        ("video", "Vídeo"),
                        ("fipe", "FIPE"),
                        ("immobilizer", "Imobilizador"),
                        ("advanced_functions", "Funções avançadas"),
                    ):
                        text += f" {label}: {shown(attrs.get(key))}."
                    fact(text, "scanner_application", application["id"], current_base)
        elif intent == "PARTNER_LOOKUP":
            rows = partner_status(self._config.database, include_candidates=True)
            names = [
                r
                for r in rows
                if any(
                    t in q
                    for t in normalize_text(r["display_name"]).split()
                    if t not in {"MOTOS", "MOTO", "MULTIMARCAS"}
                )
            ]
            rows = names or rows
            for row in rows[:limit]:
                fact(
                    f"{row['display_name']}: {row['integration_status']}; habilitado: {'sim' if row['enabled'] else 'não'}. "
                    f"Motivo: {row['reason'] or 'Integração configurada no registry'}. "
                    f"Última validação manual: {shown(row['last_validation'])}.",
                    "partner_registry",
                    row["partner"],
                )
            result["total"] = len(rows)
        elif intent == "BASE_VERSION_LOOKUP":
            data = self._repository.get_base_versions(limit)
            result["total"] = data["total"]
            for row in data["items"]:
                fact(
                    f"Versão #{row['id']}; importação: {row['import_id']}; estado: {value(row['status'])}; "
                    f"veículos: {row['unique_vehicles']}; publicação: {shown(row['published_at'])}.",
                    "scanner_base_version",
                    row["id"],
                )
        elif intent == "REVIEW_LOOKUP":
            match = re.search(r"(?:REVISAO|ITEM|#)\s*#?\s*(\d+)", q)
            with DashboardRepository(self._config.database) as repo:
                rows = (
                    [repo.detail(int(match[1]), self._config.partner)]
                    if match
                    else [
                        r
                        for r in repo.queue(self._config.partner)
                        if r["state"] in {"pending", "deferred", "invalidated"}
                    ]
                )
                result["total"] = len(rows)
                for row in rows[:limit]:
                    automatic, human = row["automatic"], row.get("human_decision")
                    candidates = [
                        {k: c.get(k) for k in ("scanner_key", "manufacturer", "model", "year", "score")}
                        for c in automatic.get("candidates", [])[:3]
                    ]
                    human_text = (
                        f"{value(human['action'])}, data {human['created_at']}, motivo {shown(human.get('note'))}"
                        if human
                        else "Nenhuma decisão humana registrada"
                    )
                    fact(
                        f"Revisão #{row['id']} · {identity(row['identity'])} · parceiro {row['partner']}. "
                        f"Normalização: {shown(row['identity'])}. Automático: {value(automatic['match_type'])}; "
                        f"score existente: {shown(automatic.get('confidence'))}; motivos: {shown(automatic.get('reasons'))}; "
                        f"candidatos: {shown(candidates)}. Decisão humana: {human_text}. "
                        f"Vínculo efetivo: {shown(row['effective'].get('scanner_key'))}; estado atual: {value(row['state'])}; "
                        f"invalidação: {shown(row.get('stale_reason'))}.",
                        "review_item",
                        row["id"],
                        current_base,
                    )
        elif intent == "DEVELOPMENT_LOOKUP":
            statuses = (
                ["WAITING_INFORMATION"]
                if "AGUARDAM" in q
                else ["IN_VALIDATION"]
                if "VALIDACAO" in q
                else [key for key in STATES if key not in CLOSED]
            )
            match = re.search(r"(?:ITEM|DESENVOLVIMENTO|#)\s*#?\s*(\d+)", q)
            # Paginated reads use the existing partner-origin filters; no command service is exposed.
            rows, page = [], 0
            while True:
                data = list_items(
                    self._config.database,
                    filters={"partner": [self._config.partner], "status": [] if match else statuses},
                    size=50,
                    page=page,
                    sort="oldest",
                )
                for row in data["items"]:
                    age = max(0, (self._clock() - datetime.fromisoformat(row["status_since"])).days)
                    if (not match or row["id"] == int(match[1])) and ("30 DIAS" not in q or age > 30):
                        rows.append({**row, "days": age})
                page += 1
                if page * 50 >= data["total"]:
                    break
            result["total"] = len(rows)
            for row in rows[:limit]:
                fact(
                    f"Desenvolvimento #{row['id']}: {identity(row)}; etapa {STATES[row['status']]}; "
                    f"{row['days']} dias na etapa; prioridade {value(row['priority'])}; parceiros {shown(row['partners'])}.",
                    "development_item",
                    row["id"],
                )
        elif intent == "PRIORITIZATION_LOOKUP":
            filters = {"effective_priority": ["high"]} if "ALTA" in q else {}
            service = PrioritizationService(self._config, clock=self._clock)
            match = re.search(r"(?:PRIORIDADE|CASO|#)\s*#?\s*(\d+)", q)
            data = service.listing(filters=filters, size=min(limit, 50))
            rows = [service.detail(int(match[1]))] if match else data["items"]
            result["total"] = 1 if match else data["total"]
            result["message"] = "Prioridades persistidas; nenhuma reavaliação foi executada."
            if data["stale"]:
                result["message"] += " A avaliação existente está desatualizada."
            for row in rows:
                fact(
                    f"Prioridade #{row['id']}: {identity(row.get('evidence', {}))}; pontuação {shown(row.get('score'))}; "
                    f"sugerida {value(row.get('suggested_priority'))}; efetiva {value(row.get('effective_priority'))}; "
                    f"override humano {shown(row.get('manual_priority'))}; motivos {shown(row.get('reasons'))}.",
                    "priority_case",
                    row["id"],
                )
        elif intent == "MANAGEMENT_METRICS":
            start, end = selected_period(question, self._clock().astimezone(ZONE).date())
            report = ManagementMetricsService(self._config.database, self._config.partner, clock=self._clock).report(
                start, end
            )
            result["period"] = {"start": str(start), "end": str(end), "timezone": "America/Sao_Paulo"}
            for name, number in list(report["metrics"].items())[: max(1, limit - 2)]:
                compare = next(r for r in report["comparisons"] if r["Indicador"] == name)
                suffix = f" Período anterior equivalente: {compare['Anterior']}." if "COMPARE" in q else ""
                fact(f"{name}: {number}. {DEFINITIONS[name]}{suffix}", "management_metrics", name, report["base_id"])
            fact(
                f"Tempo de revisão: {shown(report['review_time'])}.",
                "management_metrics",
                "review_time",
                report["base_id"],
            )
            if "COMPARE" in q:
                fact(
                    f"Período anterior calculado pelo serviço: {report['previous_start']} até {report['previous_end']} (fim exclusivo).",
                    "management_metrics",
                    "comparison_period",
                    report["base_id"],
                )
        elif intent == "ALERT_LOOKUP":
            rows = [
                r
                for r in read_alerts(self._config.database, self._config.partner)["alerts"]
                if r["status"] not in {"ARQUIVADO", "RESOLVIDO"}
            ]
            rows.sort(key=lambda r: ({"CRITICA": 0, "ALTA": 1}.get(r["severity"], 2), str(r["id"])))
            result["total"] = len(rows)
            for row in rows[:limit]:
                fact(
                    f"Alerta #{row['id']}: {row['title']}; prioridade {value(row['severity'])}; estado {value(row['status'])}; "
                    f"parceiro {row['partner']}; última ocorrência {row['last_seen_at']}.",
                    "alert",
                    row["id"],
                )
        elif intent == "RECENT_CHANGES":
            start, end = selected_period(question, self._clock().astimezone(ZONE).date())
            first, last = bounds(start, end)
            with DashboardRepository(self._config.database) as repo:
                situations = repo.partner_situations(self._config.partner)
                # Fixed SELECT includes ads that have left stock for questions about new ads.
                raw = repo.connection.execute(
                    "SELECT external_id,json_extract(payload_json,'$.manufacturer'),json_extract(payload_json,'$.model'),"
                    "json_extract(payload_json,'$.year'),first_seen_at,last_seen_at,not_seen_in_latest_collection "
                    "FROM partner_advertisements WHERE partner=?",
                    (self._config.partner,),
                ).fetchall()
            recent = "APARECERAM" in q or "NOVOS" in q or "NOVAS" in q
            returning = "REAPAREC" in q
            rows = [
                r
                for r in raw
                if (
                    situations.get(r[0], {}).get("partner_status") == "Reapareceu"
                    if returning
                    else first <= datetime.fromisoformat(r[4]) < last
                    if recent
                    else not r[6]
                )
            ]
            rows.sort(key=lambda r: (r[4], r[0]), reverse=recent and not returning)
            result["total"] = len(rows)
            if recent and not returning:
                result["period"] = {"start": str(start), "end": str(end), "timezone": "America/Sao_Paulo"}
            result["message"] = "Novo anúncio não significa nova moto para a base." + (
                " Reaparecimento refere-se à última coleta observada, não a todo o histórico." if returning else ""
            )
            for row in rows[:limit]:
                fact(
                    f"Anúncio {row[0]} · {row[1]} {row[2]} {row[3]}; parceiro {self._config.partner}; "
                    f"primeira observação {row[4]}; última {row[5]}; ativo {'não' if row[6] else 'sim'}.",
                    "partner_advertisement",
                    row[0],
                )
        elif intent == "GENERAL_HELP":
            fact(
                "Posso consultar scanner, aplicações, cabos, revisão, parceiros, desenvolvimento, prioridades, "
                "indicadores, alertas e versões. Para detalhes use revisão #ID, prioridade #ID ou veículo #ID. "
                "Ausência de informação não significa ausência de suporte. Decisões exigem confirmação humana.",
                "assistant_policy",
                "read_only_v1",
            )
        else:
            result["message"] = INSUFFICIENT
        if not result["facts"] and not result.get("message"):
            result["message"] = "Nenhum registro encontrado no recorte consultado."
        if not result["total"]:
            result["total"] = len(result["facts"])
        return result
