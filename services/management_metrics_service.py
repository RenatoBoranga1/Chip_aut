"""Management definitions, temporal reconstruction and aggregates; no operational writes."""

import csv
import io
import json
import threading
import time
from collections import Counter, OrderedDict, defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from datetime import time as day_time
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

from database.management_metrics_repository import ManagementMetricsRepository, before, stamp
from matching.review_policy import complete_identity, identity, signature
from partners.registry import PartnerRegistry
from services.development_policy import CLOSED, STATES, load_development_config
from services.review_presentation import presentation

ZONE = ZoneInfo("America/Sao_Paulo")
FILTERS = (
    "manufacturer",
    "model",
    "year",
    "base_status",
    "human_status",
    "development_stage",
    "priority",
    "assigned_to",
)
CACHE = OrderedDict()
LOCK = threading.Lock()
UNKNOWN = {"match_type": "AGUARDANDO_MATCHING", "scanner_status": None, "requires_review": True}
DEFINITIONS = {
    "Novos anúncios": "IDs de anúncios cuja primeira observação ocorreu no período; inclui anúncios que saíram do estoque.",
    "Possíveis novas identidades": "Identidades completas distintas no estoque com matching não encontrado e sem ausência humana válida. Hipótese, não ausência.",
    "Ausências confirmadas no período": "Identidades distintas no estoque com ausência humana válida na base selecionada, decidida no período.",
    "Ausências confirmadas acumuladas": "Identidades distintas no estoque com ausência humana ainda válida no encerramento.",
    "Revisões abertas no período": "Itens da fila criados no período, incluindo identidades históricas.",
    "Revisões concluídas no período": "Itens distintos com ao menos uma decisão conclusiva (existe/ausente/ignorar) no período; não implica conclusão ainda válida.",
    "Revisões pendentes": "Itens de identidade vigente no estoque com estado pending, deferred ou invalidated no encerramento.",
    "Decisões alteradas": "Eventos de decisão no período com referência à decisão anterior; não conta reaproveitamento de memória.",
    "Revisões reabertas": "Itens distintos com evento de invalidação no período; não inclui reabertura inferida sem evento persistido.",
    "Desenvolvimentos ativos": "Itens vinculados ao parceiro em etapa diferente de concluída/descartada no encerramento.",
    "Entradas em desenvolvimento": "Itens vinculados ao parceiro criados no período.",
    "Desenvolvimentos concluídos": "Itens distintos que transitaram para COMPLETED no período; reabertura posterior não apaga a entrega histórica.",
    "Desenvolvimentos descartados": "Itens distintos que transitaram para DISCARDED no período.",
    "Novos alertas": "Alertas únicos por origem e ID criados no período; recorrências não são novos alertas.",
    "Alertas relevantes": "Alertas não arquivados/resolvidos de severidade ALTA ou CRITICA no encerramento, independentemente da data de criação.",
    "Cobertura conhecida": "Anúncios no estoque com resultado efetivo SUPORTADO, SEM_SUPORTE ou SUPORTE_PARCIAL na base consultada.",
}


def period(preset, today=None, custom=None):
    today = today or datetime.now(ZONE).date()
    if preset == "Personalizado":
        if not custom or len(custom) != 2:
            raise ValueError("Informe início e fim do período.")
        start, end = custom
    elif preset == "Ano atual":
        start, end = date(today.year, 1, 1), today
    else:
        days = {"Hoje": 1, "Últimos 7 dias": 7, "Últimos 30 dias": 30, "Últimos 90 dias": 90}[preset]
        start, end = today - timedelta(days=days - 1), today
    if start > end or end > today:
        raise ValueError("Período inválido: o fim deve ser entre o início e hoje.")
    return start, end


def bounds(start, end):
    return tuple(
        datetime.combine(d, day_time.min, ZONE).astimezone(timezone.utc) for d in (start, end + timedelta(days=1))
    )


def inside(value, start, end):
    parsed = stamp(value)
    return parsed is not None and start <= parsed < end


def accepts(row, filters):
    return all(
        not values or str(row.get(key) if row.get(key) is not None else "Não informado") in {str(v) for v in values}
        for key, values in filters.items()
    )


def distinct(rows, key):
    return list({r[key]: r for r in rows}.values())


def distribution(rows, field):
    return [
        {"Categoria": str(k), "Quantidade": v}
        for k, v in Counter(r.get(field) or "Não informado" for r in rows).most_common()
    ]


def duration_stats(values):
    values = [v for v in values if v is not None and v >= 0]
    return {
        "amostra": len(values),
        "média em dias": round(mean(values), 3) if values else None,
        "mediana em dias": round(median(values), 3) if values else None,
    }


def days_between(start, end):
    a, b = stamp(start), stamp(end)
    return (b - a).total_seconds() / 86400 if a and b and b >= a else None


def development_state(data, end, thresholds):
    rows, episodes, transitions = [], [], []
    by_item = defaultdict(list)
    for event in data["development_events"]:
        by_item[event["item_id"]].append(event)
    for item in data["development"]:
        row = {
            **item,
            "partner": "",
            "development_stage": None,
            "assigned_to": "",
            "priority": "Não avaliada",
            "status_since": None,
        }
        for event in sorted(by_item[item["id"]], key=lambda r: (stamp(r["created_at"]), r["id"])):
            after = event["after"]
            status = after.get("status")
            if status and status != row["development_stage"]:
                if row["development_stage"]:
                    episodes.append(
                        {
                            "id": item["id"],
                            "stage": row["development_stage"],
                            "exited_at": event["created_at"],
                            "days": days_between(row["status_since"], event["created_at"]),
                        }
                    )
                row.update(development_stage=status, status_since=event["created_at"])
                transitions.append({"id": item["id"], "stage": status, "created_at": event["created_at"]})
            if "assigned_to" in after:
                row["assigned_to"] = after["assigned_to"]
            row["updated_at"] = event["created_at"]
        row["days_in_stage"] = days_between(row["status_since"], end.isoformat())
        threshold = thresholds.get(row["development_stage"])
        row["sla_days"] = threshold
        row["overdue"] = row["days_in_stage"] is not None and threshold is not None and row["days_in_stage"] > threshold
        rows.append(row)
    return rows, episodes, transitions


def calculate(data, start, end, filters, thresholds):
    developments, episodes, transitions = development_state(data, end, thresholds)
    ads = {a["external_id"]: a for a in data["ads"]}
    reviews = {r["external_id"]: r for r in data["reviews"] if r["active"]}
    coverage = {r["advertisement"]["external_id"]: r for r in data["coverage"] if r["import_id"] == data["base_id"]}
    priorities = {
        r["entity_id"]: r
        for r in data["priorities"]
        if r["entity_id"] in ads and signature(ads[r["entity_id"]]) == r["identity_key"]
    }
    dev_by_ad = defaultdict(list)
    for origin in data["origins"]:
        dev_by_ad[origin["external_id"]].extend(d for d in developments if d["id"] == origin["item_id"])
    all_rows = []
    for external_id, ad in ads.items():
        review = reviews.get(external_id)
        entry = coverage.get(external_id, {})
        same_identity = entry and signature(entry["advertisement"]) == signature(ad)
        automatic = review["automatic"] if review else entry.get("matching", UNKNOWN) if same_identity else UNKNOWN
        effective = (
            review["effective"] if review else entry.get("effective_result", automatic) if same_identity else UNKNOWN
        )
        # Saved human coverage is not proof of a still-valid decision without its review record.
        if not review and effective.get("match_type") in {"CONFIRMADO_AUSENTE_NA_BASE", "EXATO_CONFIRMADO_HUMANAMENTE"}:
            effective = automatic
        linked = dev_by_ad[external_id]
        dev = max(linked, key=lambda r: r["id"], default={})
        row = {
            k: ad.get(k)
            for k in (
                "partner",
                "external_id",
                "manufacturer",
                "model",
                "version",
                "year",
                "first_seen",
                "active_at_end",
            )
        }
        decision = (review or {}).get("human_decision") or {}
        row.update(
            id=(review or {}).get("id"),
            identity_key=signature(ad) if complete_identity(identity(ad)) else f"incomplete:{external_id}",
            complete_identity=complete_identity(identity(ad)),
            automatic_type=automatic["match_type"],
            automatic_current=(review["automatic_import_id"] == data["base_id"]) if review else bool(same_identity),
            automatic_resolved=not automatic.get("requires_review", True),
            coverage=effective.get("scanner_status") or "SEM_STATUS",
            state=(review or {}).get("state"),
            decision_at=decision.get("created_at"),
            priority=priorities.get(external_id, {}).get("priority", "Não avaliada"),
            manual_priority=priorities.get(external_id, {}).get("manual", False),
            development_stage=dev.get("development_stage", "Sem desenvolvimento"),
            assigned_to=dev.get("assigned_to", ""),
            **presentation(automatic, effective, review),
        )
        all_rows.append(row)
    filtered = [r for r in all_rows if accepts(r, filters)]
    stock = [r for r in filtered if r["active_at_end"]]
    linked_rows = {r["external_id"]: r for r in all_rows}
    for dev in developments:
        linked = [
            linked_rows[o["external_id"]]
            for o in data["origins"]
            if o["item_id"] == dev["id"] and o["external_id"] in linked_rows
        ]
        if linked:
            sample = linked[0]
            dev.update({k: sample[k] for k in ("human_status", "base_status", "partner")})
            dev["priority"] = min(
                (r["priority"] for r in linked), key=lambda v: {"high": 0, "medium": 1, "low": 2}.get(v, 3)
            )
        dev.setdefault("human_status", "Não informado")
        dev.setdefault("base_status", "Não informado")
    developments = [r for r in developments if accepts(r, filters)]
    dev_ids = {r["id"] for r in developments}
    transitions = [r for r in transitions if r["id"] in dev_ids and inside(r["created_at"], start, end)]
    episodes = [r for r in episodes if r["id"] in dev_ids and inside(r["exited_at"], start, end)]
    # Review event metrics include historical identities, with their own identity fields.
    review_rows = []
    for review in data["reviews"]:
        source = linked_rows.get(review["external_id"], {})
        r = {
            **source,
            **{k: review["advertisement"].get(k) for k in ("manufacturer", "model", "year")},
            "id": review["id"],
            "created_at": review["created_at"],
        }
        r.update(presentation(review["automatic"], review["effective"], review))
        if accepts(r, filters):
            review_rows.append(r)
    review_ids = {r["id"] for r in review_rows}
    decisions = [
        r for r in data["decisions"] if r["review_item_id"] in review_ids and inside(r["created_at"], start, end)
    ]
    conclusive = [r for r in decisions if r["action"] in {"CONFIRMAR_MATCH", "NAO_EXISTE_NA_BASE", "IGNORAR"}]
    completed_ids = {r["review_item_id"] for r in conclusive}
    absences = distinct([r for r in stock if r["human_status"] == "Não existe na base"], "identity_key")
    alerts = []
    for alert in data["alerts"]:
        context = linked_rows.get(alert.get("external_id"), {})
        if alert.get("item_id"):
            context = next((d for d in developments if d["id"] == alert["item_id"]), {})
        if accepts(context, filters):
            alerts.append({**context, **alert})
    groups = {
        "Novos anúncios": [r for r in filtered if inside(r["first_seen"], start, end)],
        "Possíveis novas identidades": distinct(
            [
                r
                for r in stock
                if r["complete_identity"]
                and r["automatic_type"] == "NAO_ENCONTRADA_NA_BASE"
                and r["human_status"] in {"Pendente", "Em dúvida"}
                and r["automatic_current"]
            ],
            "identity_key",
        ),
        "Ausências confirmadas no período": [r for r in absences if inside(r["decision_at"], start, end)],
        "Ausências confirmadas acumuladas": absences,
        "Revisões abertas no período": [r for r in review_rows if inside(r["created_at"], start, end)],
        "Revisões concluídas no período": [r for r in review_rows if r["id"] in completed_ids],
        "Revisões pendentes": [r for r in stock if r["id"] and r["state"] in {"pending", "deferred", "invalidated"}],
        "Decisões alteradas": [r for r in decisions if r["previous_decision_id"]],
        "Revisões reabertas": distinct(
            [
                r
                for r in data["review_events"]
                if r["review_item_id"] in review_ids and inside(r["created_at"], start, end)
            ],
            "review_item_id",
        ),
        "Desenvolvimentos ativos": [
            r for r in developments if r["development_stage"] and r["development_stage"] not in CLOSED
        ],
        "Entradas em desenvolvimento": [r for r in developments if inside(r["created_at"], start, end)],
        "Desenvolvimentos concluídos": [
            r for r in developments if r["id"] in {t["id"] for t in transitions if t["stage"] == "COMPLETED"}
        ],
        "Desenvolvimentos descartados": [
            r for r in developments if r["id"] in {t["id"] for t in transitions if t["stage"] == "DISCARDED"}
        ],
        "Novos alertas": [r for r in alerts if inside(r["created_at"], start, end)],
        "Alertas relevantes": [
            r for r in alerts if r["severity"] in {"ALTA", "CRITICA"} and r["status"] in {"NOVO", "LIDO"}
        ],
        "Cobertura conhecida": [r for r in stock if r["coverage"] in {"SUPORTADO", "SEM_SUPORTE", "SUPORTE_PARCIAL"}],
    }
    first_conclusion = {}
    for d in sorted(conclusive, key=lambda r: (stamp(r["created_at"]), r["id"])):
        first_conclusion.setdefault(d["review_item_id"], d)
    earlier_conclusions = {
        d["review_item_id"]
        for d in data["decisions"]
        if before(d["created_at"], start) and d["action"] in {"CONFIRMAR_MATCH", "NAO_EXISTE_NA_BASE", "IGNORAR"}
    }
    review_times = [
        days_between(r["created_at"], first_conclusion[r["id"]]["created_at"])
        for r in review_rows
        if r["id"] in first_conclusion and r["id"] not in earlier_conclusions
    ]
    stage_times = [
        {"Etapa": STATES[k], **duration_stats([e["days"] for e in episodes if e["stage"] == k])}
        for k in STATES
        if k not in CLOSED
    ]
    total_times = [
        days_between(
            r["created_at"],
            min(t["created_at"] for t in transitions if t["id"] == r["id"] and t["stage"] == "COMPLETED"),
        )
        for r in groups["Desenvolvimentos concluídos"]
    ]
    history = {}
    for entry in data["coverage"]:
        if not inside(entry["evaluated_at"], start, end):
            continue
        if data.get("requested_version") and entry["import_id"] != data["requested_version"]:
            continue
        ad = entry["advertisement"]
        # Only identity filters apply to independent historical evaluations; others require endpoint linkage.
        context = {
            **linked_rows.get(ad["external_id"], {}),
            **{k: ad.get(k) for k in ("manufacturer", "model", "year")},
        }
        if not accepts(context, filters):
            continue
        day = stamp(entry["evaluated_at"]).astimezone(ZONE).date().isoformat()
        history[(day, entry["import_id"], ad["external_id"])] = entry
    coverage_series, matching_series = Counter(), Counter()
    for (day, base_id, _), entry in history.items():
        effective = entry.get("effective_result") or entry.get("matching") or UNKNOWN
        status = (
            "Ausência humana (na avaliação)"
            if effective["match_type"] == "CONFIRMADO_AUSENTE_NA_BASE"
            else effective.get("scanner_status") or "SEM_STATUS"
        )
        coverage_series[(day, base_id, status)] += 1
        matching_series[(day, base_id, entry["matching"]["match_type"])] += 1

    def series(counter):
        return [
            {"Data": day, "Base": base, "Categoria": category, "Quantidade": count}
            for (day, base, category), count in sorted(counter.items())
        ]

    human_trend = Counter((stamp(d["created_at"]).astimezone(ZONE).date().isoformat(), d["action"]) for d in decisions)
    recurring = defaultdict(set)
    for observation in data["observations"]:
        ad = observation["payload"]
        if (
            ad["external_id"] in {r["external_id"] for r in filtered}
            and inside(ad.get("collected_at"), start, end)
            and complete_identity(identity(ad))
        ):
            recurring[signature(ad)].add(ad["external_id"])
    recurrence = [{**json.loads(key), "Anúncios distintos": len(ids)} for key, ids in recurring.items() if len(ids) > 1]
    decision_cases = {r["review_item_id"] for r in decisions}
    created_ids = {r["id"] for r in groups["Revisões abertas no período"]}
    dev_cohort = {r["id"] for r in groups["Entradas em desenvolvimento"]}

    def ratio(name, numerator, denominator):
        return {
            "Indicador": name,
            "Numerador": numerator,
            "Denominador": denominator,
            "Percentual": round(numerator / denominator * 100, 2) if denominator else None,
        }

    rates = [
        ratio(
            "Decisões reaproveitadas / anúncios com decisão conclusiva válida",
            sum(r["state"] == "reused" for r in stock),
            sum(r["human_status"] in {"Existe na base", "Não existe na base"} for r in stock),
        ),
        ratio(
            "Matching automático resolvido / anúncios com matching na base consultada",
            sum(r["automatic_resolved"] and r["automatic_current"] for r in stock),
            sum(r["automatic_current"] for r in stock),
        ),
        ratio("Conclusivas / casos com decisão no período", len(completed_ids), len(decision_cases)),
        ratio(
            "Novas revisões com conclusão no período / novas revisões",
            len(created_ids & completed_ids),
            len(created_ids),
        ),
        ratio(
            "Novos desenvolvimentos concluídos no período / novos desenvolvimentos",
            len(dev_cohort & {r["id"] for r in groups["Desenvolvimentos concluídos"]}),
            len(dev_cohort),
        ),
        ratio("Cobertura conhecida / anúncios no estoque", len(groups["Cobertura conhecida"]), len(stock)),
    ]
    bases = [
        r
        for r in data["base"]
        if accepts(r, {k: v for k, v in filters.items() if k in {"manufacturer", "model", "year"}})
    ]
    old_base = {
        r["key"]: r
        for r in data.get("previous_base", [])
        if accepts(r, {k: v for k, v in filters.items() if k in {"manufacturer", "model", "year"}})
    }
    new_base = {r["key"]: r for r in bases}
    comparison = (data["version"] or {}).get("publication", {}).get("comparison")
    base_stats = {
        "Total": len(bases),
        "Adicionadas": len(new_base.keys() - old_base.keys()),
        "Removidas": len(old_base.keys() - new_base.keys()),
        "Alteradas": sum(
            {k: v for k, v in old_base[key].items() if k != "record_count"}
            != {k: v for k, v in new_base[key].items() if k != "record_count"}
            for key in new_base.keys() & old_base.keys()
        ),
        "Decisões válidas reavaliadas nesta base": len(
            {
                r["human_decision"]["id"]
                for r in data["reviews"]
                if r["id"] in review_ids
                and r["automatic_import_id"] == data["base_id"]
                and r["human_decision"]
                and not r["stale_reason"]
            }
        ),
        "Casos com revalidação solicitada na publicação": (data["version"] or {}).get("revalidation_required"),
        "Eventos de invalidação nesta base": (data["version"] or {}).get("revalidation_events"),
    }
    if comparison and not any(filters.get(k) for k in ("manufacturer", "model", "year")):
        base_stats.update(
            Adicionadas=comparison["added"], Removidas=comparison["removed"], Alteradas=comparison["changed"]
        )
    return {
        "base_stats": base_stats,
        "base_id": data["base_id"],
        "human_distribution": [
            {**r, "Percentual": round(r["Quantidade"] / len(stock) * 100, 2)}
            for r in distribution(stock, "human_status")
        ],
        "development_distribution": [
            {"Etapa": label, "Quantidade": sum(r["development_stage"] == k for r in developments)}
            for k, label in STATES.items()
        ],
        "metrics": {k: len(v) for k, v in groups.items()},
        "details": groups,
        "stock": stock,
        "all_rows": all_rows,
        "development": developments,
        "review_time": duration_stats(review_times),
        "development_time": duration_stats(total_times),
        "stage_times": stage_times,
        "stalled": sorted(groups["Desenvolvimentos ativos"], key=lambda r: r["days_in_stage"] or 0, reverse=True)[:10],
        "overdue": [r for r in developments if r["overdue"]],
        "coverage_series": series(coverage_series),
        "matching_series": series(matching_series),
        "human_series": [
            {"Data": day, "Categoria": action, "Quantidade": count}
            for (day, action), count in sorted(human_trend.items())
        ],
        "recurrence": sorted(recurrence, key=lambda r: -r["Anúncios distintos"]),
        "rates": rates,
        "alerts": alerts,
        "base": bases,
        "version": data["version"],
        "availability": {
            "priorities": "priority_cases" in data["tables"],
            "scanner_versions": "scanner_versions" in data["tables"],
        },
    }


def fingerprint(path):
    result = []
    for suffix in ("", "-wal"):
        file = Path(str(path) + suffix)
        stat = file.stat() if file.exists() else None
        result.append((stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size) if stat else None)
    return tuple(result)


class ManagementMetricsService:
    def __init__(self, path, partner="wr_motos", clock=None):
        PartnerRegistry().get(partner)
        self.path, self.partner = Path(path).resolve(), partner
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.repository = ManagementMetricsRepository(self.path)

    def report(self, start, end, filters=None, version=None, cached=True):
        now = self.clock()
        period("Personalizado", now.astimezone(ZONE).date(), (start, end))
        filters = {k: v for k, v in (filters or {}).items() if v}
        if set(filters) - set(FILTERS):
            raise ValueError("Filtro gerencial desconhecido")
        thresholds = load_development_config()["stale_days"]
        first, last = bounds(start, end)
        last = min(last, now)
        previous_end = first
        previous_start = first - (last - first)
        key = (
            str(self.path),
            fingerprint(self.path),
            self.partner,
            start,
            end,
            int(now.timestamp() // 30),
            version,
            json.dumps(filters, sort_keys=True),
            json.dumps(thresholds, sort_keys=True),
        )
        with LOCK:
            if cached and key in CACHE:
                return deepcopy(CACHE[key])
        started = time.perf_counter()
        current_data, previous_data = self.repository.pair(self.partner, last, previous_end, version)
        current_data["requested_version"] = version
        previous_data["requested_version"] = version
        current = calculate(current_data, first, last, filters, thresholds)
        previous = calculate(previous_data, previous_start, previous_end, filters, thresholds)
        current.update(
            start=start.isoformat(),
            end=end.isoformat(),
            cutoff=last.isoformat(),
            previous_start=previous_start.isoformat(),
            previous_end=previous_end.isoformat(),
            previous_base_id=previous["base_id"],
            previous_review_time=previous["review_time"],
            partner=self.partner,
            filters=filters,
            comparisons=[
                {
                    "Indicador": name,
                    "Atual": value,
                    "Anterior": previous["metrics"][name],
                    "Variação": value - previous["metrics"][name],
                    "Percentual": round((value - previous["metrics"][name]) / previous["metrics"][name] * 100, 2)
                    if previous["metrics"][name]
                    else None,
                }
                for name, value in current["metrics"].items()
            ],
            elapsed_seconds=round(time.perf_counter() - started, 4),
        )
        with LOCK:
            CACHE[key] = deepcopy(current)
            while len(CACHE) > 12:
                CACHE.popitem(last=False)
        return current


def csv_export(report):
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")

    def safe(value):
        value = str(value if value is not None else "")
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value

    writer.writerow(["inicio", "fim", "corte_utc", "parceiro", "base", "filtros", "indicador", "valor", "definicao"])
    for name, value in report["metrics"].items():
        writer.writerow(
            [
                safe(v)
                for v in (
                    report["start"],
                    report["end"],
                    report["cutoff"],
                    report["partner"],
                    report["base_id"],
                    json.dumps(report["filters"], ensure_ascii=False),
                    name,
                    value,
                    DEFINITIONS[name],
                )
            ]
        )
    aggregates = [
        ("Tempo até primeira conclusão de revisão", report["review_time"]),
        ("Tempo de desenvolvimento concluído", report["development_time"]),
        ("Base selecionada", report["base_stats"]),
    ]
    aggregates.extend(
        ("Etapa: " + row["Etapa"], {k: v for k, v in row.items() if k != "Etapa"}) for row in report["stage_times"]
    )
    aggregates.extend((row["Indicador"], {k: v for k, v in row.items() if k != "Indicador"}) for row in report["rates"])
    aggregates.extend(
        ("Comparação: " + row["Indicador"], {k: v for k, v in row.items() if k != "Indicador"})
        for row in report["comparisons"]
    )
    for label, stats in aggregates:
        for stat, value in stats.items():
            writer.writerow(
                [
                    safe(v)
                    for v in (
                        report["start"],
                        report["end"],
                        report["cutoff"],
                        report["partner"],
                        report["base_id"],
                        json.dumps(report["filters"], ensure_ascii=False),
                        f"{label}: {stat}",
                        value,
                        "Dicionário: docs/DICIONARIO_INDICADORES.md. Tempo em dias corridos; vazio significa indisponível.",
                    )
                ]
            )
    return ("\ufeff" + output.getvalue()).encode("utf-8")
