import csv
import json
from collections import Counter
from dataclasses import asdict


def write_collection_report(collection_id, result, destination):
    destination.mkdir(parents=True, exist_ok=True)
    ads = result.advertisements
    group_counts = Counter(ad.normalized_key for ad in ads if ad.normalized_key)
    unknown = [a for a in ads if not a.manufacturer or not a.model]
    summary = {
        "collection_id": collection_id,
        "partner": result.partner,
        "collected_at": result.collected_at,
        "complete": result.complete,
        "cached": result.cached,
        "advertisements": len(ads),
        "unique_vehicle_keys": len(group_counts),
        "ads_without_group_key": sum(a.normalized_key is None for a in ads),
        "manufacturers": dict(sorted(Counter(a.manufacturer or "NAO_INTERPRETADA" for a in ads).items())),
        "with_year": sum(a.year is not None for a in ads),
        "without_year": sum(a.year is None for a in ads),
        "zero_km": sum(a.zero_km is True for a in ads),
        "used": sum(a.zero_km is False for a in ads),
        "unknown_zero_km": sum(a.zero_km is None for a in ads),
        "with_parse_warnings": sum(bool(a.parse_warnings) for a in ads),
        "unparsed_advertisements": len(unknown),
        "unparsed_cards_without_id": sum(e["code"] == "UNPARSED_CARD" for e in result.errors),
        "duration_seconds": result.duration_seconds,
        "method": result.method,
        "pages": result.pages,
        "errors": result.errors,
        "metadata": result.metadata,
        "group_counts": dict(group_counts),
    }
    for file, value in (("summary.json", summary), ("advertisements.json", [asdict(a) for a in ads])):
        (destination / file).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    with (destination / "advertisements.csv").open("w", newline="", encoding="utf-8-sig") as file:
        columns = [
            "external_id",
            "manufacturer",
            "model",
            "version",
            "year",
            "source_url",
            "normalized_key",
            "collected_at",
            "price",
            "mileage",
            "zero_km",
        ]
        writer = csv.DictWriter(file, fieldnames=columns, delimiter=";")
        writer.writeheader()
        for ad in ads:
            data = asdict(ad)
            writer.writerow(
                {
                    k: "'" + str(data[k])
                    if isinstance(data[k], str) and data[k].startswith(("=", "+", "-", "@"))
                    else data[k]
                    for k in columns
                }
            )
    lines = [
        "# Relatório — Milestone 3: WR Motos",
        "",
        f"Coleta {collection_id}, em {result.collected_at}. Completa: {result.complete}. Cache: {result.cached}.",
        "",
        f"Método: {result.method}. Duração: {result.duration_seconds:.3f} s.",
        "",
        f"Anúncios distintos: **{len(ads)}**. Chaves de veículos distintas: **{len(group_counts)}**. "
        f"Sem chave completa: {summary['ads_without_group_key']}.",
        "",
        f"Com ano: {summary['with_year']}. Sem ano: {summary['without_year']}. "
        f"Identidade não interpretada: {len(unknown)}. Cards sem ID interpretável: {summary['unparsed_cards_without_id']}.",
        "",
        "Montadoras (anúncios): " + json.dumps(summary["manufacturers"], ensure_ascii=False),
        "",
        f"Páginas/filtros visitados: {len(result.pages)}. Ocorrências duplicadas por ID: "
        f"{result.metadata.get('duplicate_occurrences', 0)}. Erros: {len(result.errors)}.",
        "",
        f"0 km: {summary['zero_km']}. Usados: {summary['used']}. Indefinidos: {summary['unknown_zero_km']}.",
        "Contagens por filtro: " + json.dumps(result.metadata.get("scope_counts", {}), ensure_ascii=False),
        "",
        "## Exemplos reais",
        "",
        "| ID | Montadora | Modelo completo | Ano | Anúncio |",
        "|---|---|---|---:|---|",
    ]
    for ad in ads[: max(20, min(30, len(ads)))]:
        lines.append(
            f"| {ad.external_id} | {ad.manufacturer or 'Não interpretada'} | "
            f"{(ad.model or ad.raw_name).replace('|', '/')} | {ad.year or 'Ausente'} | [Abrir]({ad.source_url}) |"
        )
    lines += [
        "",
        "## Procedência e limites",
        "",
        "Fonte: [catálogo público WR Motos](https://www.wrmotos.com.br/v1/estoque/). "
        "Lista extraída das respostas HTML XHR utilizadas pelo próprio frontend; método registrado acima.",
        "",
        "Cada ID representa um anúncio; unidades do mesmo modelo permanecem distintas. "
        "A chave agrupa montadora, nome completo (incluindo versão quando escrita no título) e ano. "
        "O site não fornece versão em campo separado: version permanece null. "
        "Textos promocionais também são preservados, podendo fragmentar grupos até revisão futura.",
        "",
        "A completude exige os dois filtros 0 KM. Não se presume que os filtros "
        "funcionem corretamente no servidor; repetições são deduplicadas pelo ID, com contagem registrada.",
        "",
        "Matching/cobertura são executados separadamente por app.coverage. Cache não atualiza last_seen. "
        "Coletas incompletas não marcam anúncios ausentes. Snapshots e first/last_seen ficam no SQLite.",
        "",
        "## Erros",
        "",
        json.dumps(result.errors, ensure_ascii=False, indent=2),
        "",
    ]
    (destination / "RELATORIO_MILESTONE_3.md").write_text("\n".join(lines), encoding="utf-8")
    return summary
