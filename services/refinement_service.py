"""Offline before/after audit on one collection and one immutable scanner snapshot."""

import json
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace

from rapidfuzz import fuzz

from database.matching_repository import MatchingRepository
from database.partner_repository import PartnerRepository
from matching.fuzzy_matcher import combined_model, compare_features, features
from matching.identity import CATEGORIES
from matching.matcher import Matcher
from matching.models import MotorcycleQuery
from matching.rules import DEFAULT_MATCHING_RULES, load_matching_rules
from scanner_base.normalizer import normalize_manufacturer
from services.coverage_service import build_coverage

ABSENCE = "PROVAVELMENTE_NAO_SUPORTADA_NA_BASE"


def diagnostics(query, engine):
    policy = engine.rules.identity_policy.get("diagnostics", {"near_similarity": 75, "max_candidates": 10})
    manufacturer, _ = engine.identity.manufacturer(normalize_manufacturer(query.manufacturer, engine.aliases))
    model, _ = engine.identity.model(manufacturer, combined_model(query.model, query.version))
    source = features(model, manufacturer)
    candidates, exact_other_years = [], []
    same_manufacturer = 0
    for (brand, year), group in engine.groups.items():
        if brand != manufacturer:
            continue
        same_manufacturer += len(group)
        for motorcycle, target in group:
            rejected = []
            if year != query.year:
                rejected.append("ANO_DIVERGENTE")
            candidate = compare_features(source, motorcycle, target, engine.rules, True)
            if candidate is None:
                rejected.append("ASSINATURA_NUMERICA_DIVERGENTE")
            else:
                rejected.extend(candidate.blockers)
                if candidate.confidence < engine.rules.candidate_threshold:
                    rejected.append("SCORE_ABAIXO_DO_LIMIAR")
            similarity = round(fuzz.token_sort_ratio(" ".join(source.tokens), " ".join(target.tokens)), 2)
            if source.compact == target.compact and year != query.year:
                exact_other_years.append({"key": motorcycle.key, "year": year})
            candidates.append(
                {
                    "scanner_key": motorcycle.key,
                    "model": motorcycle.model,
                    "year": year,
                    "scanner_status": motorcycle.status,
                    "tokens": target.tokens,
                    "diagnostic_similarity": similarity,
                    "matching_score": candidate.confidence if candidate else None,
                    "rejection_reasons": rejected,
                    "query_only_tokens": sorted((Counter(source.tokens) - Counter(target.tokens)).elements()),
                    "base_only_tokens": sorted((Counter(target.tokens) - Counter(source.tokens)).elements()),
                }
            )
    candidates.sort(key=lambda c: (-c["diagnostic_similarity"], c["year"] != query.year, c["scanner_key"]))
    same_year = [c for c in candidates if c["year"] == query.year]
    # Absence is conservative: a known exact model in other years, with no plausible
    # same-year spelling/trim candidate. Diagnostic retrieval never confirms a match.
    near_same_year = [
        c
        for c in same_year
        if c["diagnostic_similarity"] >= policy["near_similarity"]
        or (c["matching_score"] is not None and c["matching_score"] >= engine.rules.candidate_threshold)
    ]
    return {
        "tokens": source.tokens,
        "numeric_signature": source.displacement,
        "manufacturer_entries": same_manufacturer,
        "same_year_entries": len(same_year),
        "exact_identity_other_years": exact_other_years,
        "near_same_year": near_same_year[: policy["max_candidates"]],
        "diagnostic_candidates": candidates[: policy["max_candidates"]],
        "same_year_candidates": same_year[: policy["max_candidates"]],
        "rejection_totals": dict(Counter(reason for c in candidates for reason in c["rejection_reasons"])),
        "note": "Similaridade diagnóstica busca explicações inclusive em outros anos; não é matching nem suporte.",
    }


def classify_causes(before, after, diagnostic):
    evidence = after["identity_evidence"]
    steps = evidence.get("query_steps", []) + [s for seq in evidence.get("candidate_steps", {}).values() for s in seq]
    ids = {s["rule_id"] for s in steps}
    causes = []
    if any("promotion" in rule for rule in ids):
        causes.append("TITULO_PROMOCIONAL")
    if any("spelling" in rule for rule in ids):
        causes.append("GRAFIA_DIFERENTE")
    if "yamaha-fazer-token-order" in ids:
        causes.append("ORDEM_DE_PALAVRAS")
    if "repeated-manufacturer-prefix" in ids:
        causes.append("FABRICANTE_REPETIDO")
    if "bmw-40-years-translation" in ids:
        causes.append("TRADUCAO_DE_EDICAO_ESPECIAL")
    if "repeated-dct-description" in ids:
        causes.append("VERSAO_REPETIDA")
    if before["match_type"] == "AMBIGUOUS" or after["match_type"] == "AMBIGUOUS":
        causes.append("VERSAO_OMITIDA_AMBIGUA")
    blockers = {b for c in after["candidates"] for b in c["blockers"]}
    if "VERSAO_DIFERENTE_OU_INCOMPLETA" in blockers:
        causes.append("VERSAO_SUFIXO_OU_EDICAO")
    if "INFORMACAO_NUMERICA_AUSENTE" in blockers:
        causes.append("INFORMACAO_NUMERICA_OMITIDA")
    if "NUMEROS_DE_MODELO_OU_VERSAO_DIFERENTES" in blockers:
        causes.append("NUMEROS_DIVERGENTES")
    if diagnostic["exact_identity_other_years"]:
        causes.append("IDENTIDADE_EXISTE_EM_OUTROS_ANOS")
    if not diagnostic["manufacturer_entries"]:
        causes.append("FABRICANTE_AUSENTE_NA_BASE")
    if after["match_type"] == "NAO_ENCONTRADA_NA_BASE":
        causes.append("AUSENCIA_A_INVESTIGAR")
    return causes or ["IDENTIDADE_EXATA" if after["scanner_key"] else "DIVERGENCIA_TEXTUAL_NAO_CONFIRMADA"]


def probable_absence(ad, after, diagnostic):
    if after["match_type"] != "NAO_ENCONTRADA_NA_BASE":
        return None
    if not ad["manufacturer"] or not ad["model"] or not ad["year"]:
        return None
    if set(ad["parse_warnings"]) - {"FILTROS_ZERO_KM_CONFLITANTES"}:
        return None
    if not diagnostic["manufacturer_entries"]:
        return "Montadora extraída do catálogo não possui registros na versão consultada, após aliases conhecidos."
    if diagnostic["exact_identity_other_years"] and not diagnostic["near_same_year"]:
        return "Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano."
    return None


def analyze_refinement(collection_id, baseline_coverage_id, database, destination, rules_path=DEFAULT_MATCHING_RULES):
    with PartnerRepository(database) as repo:
        row = repo.connection.execute(
            "SELECT report_json FROM coverage_runs WHERE id=?", (baseline_coverage_id,)
        ).fetchone()
        if not row:
            raise ValueError("Relatório de cobertura anterior não encontrado")
        baseline = json.loads(row[0])
        collection = repo.get_collection(collection_id)
    with MatchingRepository(database) as repo:
        import_id, scanner_policy, base = repo.matching_snapshot()
        memory = repo.load_memory()
    if baseline["collection_id"] != collection_id or baseline["import_id"] != import_id:
        raise ValueError("Comparação exige a mesma coleta e versão da base")
    old_items = {i["advertisement"]["external_id"]: i for group in baseline["groups"].values() for i in group}
    if set(old_items) != {a.external_id for a in collection.advertisements}:
        raise ValueError("Inventários antes/depois não correspondem")
    if any(asdict(a) != old_items[a.external_id]["advertisement"] for a in collection.advertisements):
        raise ValueError("Observações foram alteradas desde o baseline")
    rules = load_matching_rules(rules_path)
    engine = Matcher(base, scanner_policy["manufacturer_aliases"], rules, memory)
    after_report = build_coverage(collection_id, database, destination / "coverage", rules_path)
    if after_report["import_id"] != import_id:
        raise ValueError("Base mudou durante análise; repita com snapshot estável")
    new_items = {i["advertisement"]["external_id"]: i for group in after_report["groups"].values() for i in group}
    ablations = {}
    for category in CATEGORIES:
        for rule in rules.identity_policy.get(category, []):
            policy = deepcopy(rules.identity_policy)
            policy[category] = [r for r in policy[category] if r["id"] != rule["id"]]
            ablations[rule["id"]] = Matcher(
                base, scanner_policy["manufacturer_aliases"], replace(rules, identity_policy=policy), memory
            )
    inventory, resolved, absent, changed = [], [], [], []
    for identifier, item in new_items.items():
        ad, after = item["advertisement"], item["matching"]
        before = old_items[identifier]["matching"]
        query = MotorcycleQuery(ad["manufacturer"] or "", ad["model"] or "", ad["year"], ad["version"] or "")
        diag = diagnostics(query, engine)
        solved = after["match_type"] == "EXATO_NORMALIZADO" and before["match_type"] not in {
            "EXATO_NORMALIZADO",
            "CONFIRMADO_MANUALMENTE",
        }
        essential = []
        if solved:
            for rule_id, alternative in ablations.items():
                result = alternative.match(query)
                if result.match_type != "EXATO_NORMALIZADO" or result.scanner_key != after["scanner_key"]:
                    essential.append(rule_id)
        entry = {
            "advertisement": ad,
            "before": before,
            "after": after,
            "original_tokens": features(combined_model(query.model, query.version), query.manufacturer).tokens,
            "diagnostics": diag,
            "causes": classify_causes(before, after, diag),
            "resolved": solved,
            "essential_rules": essential,
            "absence_reason": probable_absence(ad, after, diag),
        }
        inventory.append(entry)
        if solved:
            resolved.append(entry)
        if before["match_type"] != after["match_type"]:
            changed.append(entry)
        if entry["absence_reason"]:
            absent.append(entry)
    sensitivity = {}
    queries = [
        MotorcycleQuery(a.manufacturer or "", a.model or "", a.year, a.version or "") for a in collection.advertisements
    ]
    for name, weights in {
        "current": rules.weights,
        "more_token_order": {"token_sort": 0.8, "token_set": 0.1, "compact": 0.1},
        "more_compact": {"token_sort": 0.5, "token_set": 0.2, "compact": 0.3},
    }.items():
        experiment = Matcher(base, scanner_policy["manufacturer_aliases"], replace(rules, weights=weights), memory)
        sensitivity[name] = {
            "weights": weights,
            "distribution": dict(Counter(r.match_type for r in experiment.match_many(queries))),
        }
    report = {
        "collection_id": collection_id,
        "import_id": import_id,
        "baseline_coverage_id": baseline_coverage_id,
        "after_coverage_id": after_report["coverage_run_id"],
        "policy": rules.to_dict(),
        "before": dict(Counter(i["before"]["match_type"] for i in inventory)),
        "after": dict(Counter(i["after"]["match_type"] for i in inventory)),
        "resolved": len(resolved),
        "changed_classification": len(changed),
        "transitions": dict(Counter(f"{i['before']['match_type']} -> {i['after']['match_type']}" for i in changed)),
        "resolved_by_essential_rule": dict(Counter(r for item in resolved for r in item["essential_rules"])),
        "rule_count_note": "Ablação individual: regras indispensáveis ao resultado. Regras conjuntas podem contar o mesmo anúncio; não somar para obter total.",
        "causes": dict(Counter(c for i in inventory for c in i["causes"])),
        "weight_sensitivity": sensitivity,
        "weight_decision": "Pesos mantidos. Sem rótulos humanos, variação de contagem não mede precisão nem autoriza calibrar scores.",
        "probable_absence_count": len(absent),
        "absence_label": ABSENCE,
        "absence_note": "Hipótese sobre identidades registradas nesta versão da planilha, não diagnóstico de SEM_SUPORTE. Anos não são interpolados. Demais não encontrados permanecem inconclusivos.",
        "inventory": inventory,
    }
    destination.mkdir(parents=True, exist_ok=True)
    for filename, payload in (
        ("inventory.json", report),
        ("probable_absence.json", {"label": ABSENCE, "note": report["absence_note"], "items": absent}),
    ):
        (destination / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def cell(value):
        return str(value).replace("|", " / ").replace("\n", " ")

    lines = [
        "# Refinamento de matching — Milestone 3.1",
        "",
        f"Coleta {collection_id}; base {import_id}.",
        "",
        "| Tipo | Antes | Depois |",
        "|---|---:|---:|",
    ]
    for kind in sorted(set(report["before"]) | set(report["after"])):
        lines.append(f"| {kind} | {report['before'].get(kind, 0)} | {report['after'].get(kind, 0)} |")
    lines += [
        "",
        f"Resolvidos por equivalências explícitas: {len(resolved)}.",
        report["rule_count_note"],
        "",
        "## Casos resolvidos",
        "",
        "| ID / anúncio | Ano | Antes | Chave da base | Regra indispensável |",
        "|---|---|---|---|---|",
    ]
    for item in resolved:
        ad = item["advertisement"]
        lines.append(
            f"| [{ad['external_id']}]({ad['source_url']}) {cell(ad['raw_name'])} | {ad['year']} | {item['before']['match_type']} | {cell(item['after']['scanner_key'])} | {cell(', '.join(item['essential_rules']))} |"
        )
    lines += [
        "",
        f"## {ABSENCE} ({len(absent)})",
        "",
        report["absence_note"],
        "",
        "| ID / anúncio | Ano | Evidência |",
        "|---|---|---|",
    ]
    for item in absent:
        ad = item["advertisement"]
        years = [c["year"] for c in item["diagnostics"]["exact_identity_other_years"]]
        lines.append(
            f"| [{ad['external_id']}]({ad['source_url']}) {cell(ad['raw_name'])} | {ad['year']} | {cell(item['absence_reason'])} Outros anos: {years} |"
        )
    lines += ["", "## Ambiguidades preservadas", ""]
    for item in inventory:
        if item["after"]["match_type"] == "AMBIGUOUS":
            ad = item["advertisement"]
            lines.append(
                f"- {ad['external_id']}: {ad['raw_name']}, {ad['year']}; "
                + "; ".join(c["model"] for c in item["after"]["candidates"])
            )
    lines += [
        "",
        "## Pesos e limites",
        "",
        report["weight_decision"],
        "Os filtros 0 km continuam inconsistentes: estado indefinido e alerta preservados. "
        "O inventário JSON contém todos os anúncios, tokens, scores, diferenças, rejeições e causas. "
        "Cobertura completa e candidatos estão em coverage/COBERTURA.md.",
        "",
    ]
    (destination / "REFINAMENTO.md").write_text("\n".join(lines), encoding="utf-8")
    return {key: value for key, value in report.items() if key != "inventory"}
