"""Join persisted advertisements to existing matching, without inferring support."""

import json
from collections import Counter
from dataclasses import asdict

from database.matching_repository import MatchingRepository
from database.partner_repository import PartnerRepository
from database.review_repository import ReviewRepository
from matching.models import MotorcycleQuery
from matching.rules import DEFAULT_MATCHING_RULES
from services.matching_service import match_many
from services.review_service import collection_changes

GROUPS = (
    "CONFIRMADO_AUSENTE_NA_BASE",
    "NAO_ENCONTRADA_NA_BASE",
    "CORRESPONDENCIA_PROVAVEL",
    "REVISAR",
    "SEM_SUPORTE",
    "SUPORTE_PARCIAL",
    "EM_ANALISE",
    "SEM_STATUS",
    "SUPORTADO",
)


def build_coverage(collection_id, database, destination, rules_path=DEFAULT_MATCHING_RULES, *, update_queue=True):
    with PartnerRepository(database) as repo:
        collection = repo.get_collection(collection_id)
    ads = collection.advertisements
    queries = [MotorcycleQuery(a.manufacturer or "", a.model or "", a.year, a.version or "") for a in ads]
    runs = match_many(queries, database, rules_path)
    reviews = [None] * len(ads)
    if update_queue:
        with ReviewRepository(database) as repo:
            reviews = repo.sync(collection_id, [(asdict(ad), run["run_id"]) for ad, run in zip(ads, runs)])
    if runs:
        import_id = runs[0]["import_id"]
    else:
        with MatchingRepository(database) as repo:
            import_id, _, _ = repo.matching_snapshot()
    groups = {key: [] for key in GROUPS}
    for ad, run, review in zip(ads, runs, reviews):
        automatic = asdict(run["result"])
        result = review["effective"] if review else automatic
        if result["match_type"] in {"NAO_ENCONTRADA_NA_BASE", "CORRESPONDENCIA_PROVAVEL", "CONFIRMADO_AUSENTE_NA_BASE"}:
            group = result["match_type"]
        elif result["requires_review"] or not result["scanner_key"]:
            group = "REVISAR"
        else:
            group = result["scanner_status"]
        if group not in groups:
            group = "REVISAR"
        groups[group].append(
            {
                "advertisement": asdict(ad),
                "matching_run_id": run["run_id"],
                "matching": automatic,
                "automatic_result": automatic,
                "human_decision": review["human_decision"] if review else None,
                "effective_result": result,
                "review_item_id": review["id"] if review else None,
                "review_state": review["state"] if review else None,
            }
        )
    report = {
        "collection_id": collection_id,
        "import_id": import_id,
        "complete_collection": collection.complete,
        "operational_review_applied": update_queue,
        "cached": collection.cached,
        "collected_at": collection.collected_at,
        "advertisements": len(ads),
        "collection_changes": collection_changes(collection_id, database),
        "counts": {key: len(value) for key, value in groups.items()},
        "review_queue": {
            "items": sum(r is not None for r in reviews),
            "states": dict(Counter(r["state"] for r in reviews if r)),
            "reused": sum(r is not None and r["memory"]["reused"] for r in reviews),
        },
        "groups": groups,
        "limitations": "Correspondência provável não confirma suporte. Ausência de candidato não prova ausência na base. "
        "Coleta parcial não representa o catálogo inteiro. Status refere-se aos sistemas registrados na base.",
    }
    with PartnerRepository(database) as repo:
        report["coverage_run_id"] = repo.save_coverage(collection_id, import_id, report)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Atenção à cobertura — WR Motos",
        "",
        f"Coleta {collection_id}; versão da base {import_id}.",
        f"Coleta completa: {collection.complete}. Anúncios: {len(ads)}.",
        "",
        report["limitations"],
        "",
    ]

    def cell(value):
        return str(value if value is not None else "—").replace("|", " / ").replace("\n", " ")

    for group, items in groups.items():
        lines += [
            f"## {group} ({len(items)})",
            "",
            "| Anúncio / ID | Ano / 0 km | Tipo / score | Chave ou candidatos / status | Motivo |",
            "|---|---|---|---|---|",
        ]
        for item in items:
            ad, result = item["advertisement"], item["effective_result"]
            candidates = "; ".join(
                f"{c['scanner_key']} ({c['scanner_status']}; score {c['confidence']})" for c in result["candidates"]
            )
            target = (
                f"{result['scanner_key']} ({result['scanner_status']})"
                if result["scanner_key"]
                else candidates or "Sem candidato"
            )
            label = cell(ad["raw_name"]).replace("[", "(").replace("]", ")")
            lines.append(
                f"| [{label}]({ad['source_url']}) / {ad['external_id']} | {cell(ad['year'])} / {cell(ad['zero_km'])} | "
                f"{result['match_type']} / {cell(result['confidence'])} | {cell(target)} | {cell('; '.join(result['reasons']))} |"
            )
        lines.append("")
    (destination / "COBERTURA.md").write_text("\n".join(lines), encoding="utf-8")
    return report
