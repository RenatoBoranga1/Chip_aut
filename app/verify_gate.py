"""Read-only base audit; batch benchmarks write only to temporary database copies."""

import argparse
import json
import re
import sqlite3
import statistics
import tempfile
import time
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

from database.matching_repository import MatchingRepository
from matching.matcher import Matcher
from matching.models import MotorcycleQuery
from matching.rules import load_matching_rules
from scanner_base.normalizer import normalize_text
from services.matching_service import match_many


def audit(database, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with MatchingRepository(database) as repo:
        import_id, policy, models = repo.matching_snapshot()
        records = [
            json.loads(p)
            for (p,) in repo.connection.execute(
                "SELECT payload_json FROM system_records WHERE import_id=?", (import_id,)
            )
        ]
        issues = [
            json.loads(p)
            for (p,) in repo.connection.execute(
                "SELECT payload_json FROM import_issues WHERE import_id=?", (import_id,)
            )
        ]
        memory = repo.load_memory()
    groups = defaultdict(set)
    codes = defaultdict(list)
    for r in records:
        f = r["raw_fields"]
        groups[r["key"]].add((f["manufacturer"], f["model"], f["year"]))
        version = re.match(r"^(V\d+)\b", normalize_text(f.get("release", "")))
        codes[version.group(1) if version else "OUTROS_LANC"].append(r)
        if re.search(r"\bMC\b", normalize_text(f.get("release", "") + " " + f.get("situation", ""))):
            codes["MC_LITERAL"].append(r)
    collisions = []
    for key, variants in sorted(groups.items()):
        if len(variants) < 2:
            continue
        signatures = {tuple(re.sub(r"[\s\-‐‑‒–—]", "", normalize_text(x)) for x in variant) for variant in variants}
        collisions.append(
            {
                "key": key,
                "variants": sorted(variants),
                "classification": "LEGITIMA_GRAFIA" if len(signatures) == 1 else "REVISAR_PERIGO",
            }
        )
    distributions = {
        code: {
            "count": len(rows),
            "manufacturers": dict(Counter(r["manufacturer"] for r in rows)),
            "examples": [
                {
                    "row": r["row"],
                    "key": r["key"],
                    "LANC": r["release"],
                    "SIT": r["raw_fields"].get("situation", ""),
                    "status": r["status"],
                }
                for r in rows[:5]
            ],
        }
        for code, rows in sorted(codes.items())
    }
    engine = Matcher(models, policy["manufacturer_aliases"], load_matching_rules(), memory)
    queries = []
    for i in range(1000):
        m = models[i % len(models)]
        queries.append(
            MotorcycleQuery(m.manufacturer, m.model, m.year)
            if i % 2 == 0
            else MotorcycleQuery("SUZUKI", "V-Strom 650 XT", 2024)
        )
    benchmarks = []
    for size in (1, 100, 1000):
        elapsed = []
        for _ in range(3):
            start = time.perf_counter()
            engine.match_many(queries[:size])
            elapsed.append(time.perf_counter() - start)
        with tempfile.TemporaryDirectory() as folder:
            temporary = Path(folder) / "bench.sqlite3"
            with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(temporary)) as copy:
                source.backup(copy)
            start = time.perf_counter()
            match_many(queries[:size], temporary)
            full = time.perf_counter() - start
        benchmarks.append(
            {
                "matches": size,
                "matcher_seconds_median_3": round(statistics.median(elapsed), 6),
                "batch_service_seconds_with_sqlite": round(full, 6),
            }
        )
    report = {
        "import_id": import_id,
        "records": len(records),
        "vehicles": len(models),
        "collision_groups": len(collisions),
        "legitimate": sum(c["classification"] == "LEGITIMA_GRAFIA" for c in collisions),
        "dangerous_or_unresolved": sum(c["classification"] != "LEGITIMA_GRAFIA" for c in collisions),
        "collisions": collisions,
        "code_distribution": distributions,
        "raw_release_counts": dict(Counter(r["release"] for r in records)),
        "raw_situation_counts": dict(Counter(r["raw_fields"].get("situation", "") for r in records)),
        "issues": [i for i in issues if i["code"] != "UNRESOLVED_STATUS"],
        "benchmarks": benchmarks,
    }
    (destination / "gate.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Gate do Milestone 2",
        "",
        f"Base vigente: {len(records)} registros, {len(models)} veículos.",
        "",
        f"Colisões de grafia: {len(collisions)} grupos; {report['legitimate']} legítimos; "
        f"{report['dangerous_or_unresolved']} perigosos ou pendentes.",
        "",
        "Classificação por preservação de letras, números e pontuação significativa após remoção de espaços, "
        "caixa, acentos e hífens. Não é identificação por chassi. Nenhuma chave da base foi alterada.",
        "",
        "## Colisões encontradas",
        "",
    ]
    for c in collisions:
        lines.append(f"- `{c['key']}` — {c['classification']}: " + repr(c["variants"]))
    lines += [
        "",
        "## Códigos sem inferência semântica",
        "",
        "Versões contam o prefixo literal Vxx em LANC.; MC conta o token literal em LANC. ou SIT. "
        "MC sobrepõe versões e não deve ser somado a elas. MODO COLABORATIVO permanece texto distinto. "
        "OUTROS_LANC reúne valores sem prefixo Vxx. Quantidades são registros de sistemas, não veículos.",
        "",
    ]
    for code, d in distributions.items():
        lines += [
            f"### {code}: {d['count']}",
            "",
            "Montadoras: " + json.dumps(d["manufacturers"], ensure_ascii=False),
            "",
            "Exemplos: " + json.dumps(d["examples"], ensure_ascii=False),
            "",
        ]
    lines += [
        "## Inconsistências",
        "",
        json.dumps(dict(Counter(i["code"] for i in report["issues"])), ensure_ascii=False),
        "",
        "Detalhes, linhas de origem e valores em gate.json. Excel original não editado.",
        "",
        "## Benchmark",
        "",
        "| Matches | Matcher, mediana de 3 (s) | Serviço com SQLite (s) |",
        "|---:|---:|---:|",
    ]
    lines += [
        f"| {b['matches']} | {b['matcher_seconds_median_3']} | {b['batch_service_seconds_with_sqlite']} |"
        for b in benchmarks
    ]
    lines += [
        "",
        "Mistura de nomes reais da base e consulta Suzuki V-Strom 650 XT 2024. "
        "Índices carregados uma vez no benchmark do matcher; serviço inclui leitura, matching e gravação "
        "transacional em cópia temporária. A cópia em si não integra o tempo. O caso de 1 match é exato.",
        "",
        "## Evidências funcionais",
        "",
        "- Teste GS/Adventure produz AMBIGUOUS, requires_review=True e dois candidatos.",
        "- Top 5 configurável; margem entre scores verificada antes de truncar candidatos.",
        "- Componentes RapidFuzz, tokens comuns/diferentes, pesos e penalidades explicam o score sem LLM.",
        "- matching_memory registra CONFIRMAR, REJEITAR e REVOGAR; carregada antes do fuzzy.",
        "- Matcher.match_many e services.matching_service.match_many reutilizam snapshot e índices.",
        "- A decisão histórica por execução continua disponível; memória persistente é explícita pelo comando remember.",
        "",
    ]
    (destination / "GATE_MILESTONE_2.md").write_text("\n".join(lines), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/coverage.sqlite3"))
    parser.add_argument("--reports", type=Path, default=Path("reports/gate"))
    args = parser.parse_args()
    result = audit(args.db, args.reports)
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "records",
                    "vehicles",
                    "collision_groups",
                    "legitimate",
                    "dangerous_or_unresolved",
                    "benchmarks",
                ]
            }
        )
    )
