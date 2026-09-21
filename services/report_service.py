import csv
import json
from dataclasses import asdict
from pathlib import Path


def write_reports(base, report, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in (
        ("report.json", report),
        ("issues.json", base.issues),
        ("motorcycles.json", [asdict(m) for m in base.motorcycles]),
    ):
        (destination / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = [asdict(m) for m in base.motorcycles]
    with (destination / "motorcycles.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        for row in rows:
            # Spreadsheet-safe CSV; canonical, unmodified values remain in JSON/SQLite.
            row = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in row.items()}
            row = {
                k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v for k, v in row.items()
            }
            writer.writerow(row)
    text = [
        "# Moto Coverage Monitor — relatório da base",
        "",
        f"Importação: {report['import_id']}. SHA-256: `{report['sha256']}`.",
        "",
        f"Registros válidos: **{report['valid_system_records']}**. "
        f"Veículos únicos: **{report['unique_motorcycles']}**. "
        f"Montadoras/categorias: **{len(report['manufacturers'])}**.",
        "",
        f"Linhas rejeitadas: {report['rejected_rows']}. Duplicatas exatas: {report['exact_duplicate_rows']}. "
        f"Pares veículo/sistema: {report['unique_motorcycle_systems']}.",
        "",
        f"Datas: {report['earliest_date']} a {report['latest_date']}. "
        f"Leitura, validação e consolidação: {report['processing_seconds']} s.",
        "",
        "## Estrutura encontrada",
        "",
    ]
    for sheet in report["sheets"]:
        text += [
            f"- {sheet['name']}: área declarada `{sheet['dimension']}`; {sheet['populated_rows']} linhas com conteúdo.",
            "- Colunas: " + ", ".join(sheet["columns"]),
        ]
    text += [
        "",
        "## Interpretação de suporte",
        "",
        report["policy"]["notes"],
        "",
        "Sim indica suporte declarado; NÃO/NÃO LANÇAR indicam ausência de lançamento. "
        "ANALISE tem precedência sobre Sim. Valores não mapeados e conflitos permanecem SEM_STATUS. "
        "Mistura de sistemas suportados e não suportados produz SUPORTE_PARCIAL; "
        "depois aplica-se a precedência EM_ANALISE, SEM_STATUS e unanimidade.",
        "",
        "| Status agregado | Veículos |",
        "|---|---:|",
    ]
    text += [f"| {k} | {v} |" for k, v in report["motorcycle_statuses"].items()]
    text += ["", "## Montadoras e categorias", "", "| Nome normalizado | Veículos |", "|---|---:|"]
    text += [f"| {k} | {v} |" for k, v in report["manufacturers"].items()]
    text += ["", "## Inconsistências", ""]
    text += [f"- {k}: {v}." for k, v in report["issues_by_code"].items()]
    text += [
        "",
        "Detalhes e linhas de origem estão em `issues.json`. "
        "A base inclui veículos náuticos e outras categorias: não foram excluídos. "
        "KAWASSAKI é mantida como grafia suspeita até revisão. "
        "SEA-DOO e SEADOO são consolidadas pelo mapa explícito de aliases. "
        "SHINERAY/SBM, SBM e SHINERAY continuam separados.",
        "",
        "## Exemplos reais",
        "",
        "| Montadora | Modelo | Ano | Sistemas | Status |",
        "|---|---|---:|---:|---|",
    ]
    text += [
        f"| {m.manufacturer} | {m.model} | {m.year} | {m.system_count} | {m.status} |" for m in base.motorcycles[:12]
    ]
    text += ["", "## Diferença para a versão anterior", ""]
    text += [f"- {k}: {len(v)}." for k, v in report["diff"].items()]
    text += [
        "",
        "Na primeira importação, todos os veículos/sistemas são adições. "
        "Importações anteriores, valores originais e registros duplicados permanecem no SQLite.",
        "",
    ]
    (destination / "RELATORIO_BASE.md").write_text("\n".join(text), encoding="utf-8")
