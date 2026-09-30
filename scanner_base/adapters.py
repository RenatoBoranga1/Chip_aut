"""Explicit scanner layouts producing the same vehicle/system model.

Application metadata never implies coverage. Only APLICACAO GERAL contributes
records; complementary release tabs remain diagnostic evidence.
"""

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Protocol

from scanner_base.models import ParsedBase, SystemRecord
from scanner_base.normalizer import (
    normalize_manufacturer,
    normalize_model,
    normalize_text,
    normalize_year,
    normalized_key,
)
from scanner_base.parser import REQUIRED, header_map, parse_workbook

APPLICATION_HEADERS = {
    "VERS": "application_introduced_version",
    "MONTADORA": "manufacturer",
    "MODELO": "model",
    "ANO": "year",
    "SISTEMA": "system",
    "CABO": "cable",
    "TIPO DE TESTE": "test_type",
    "NOVO SISTEMA": "new_system",
    "VIDEO": "video",
    "TABELA FIPE": "fipe",
    "IMOBILIZADOR": "immobilizer",
    "FUNCOES AVANCADAS": "advanced_functions",
    "SCOOTER": "scooter",
}
ATTRIBUTES = ("new_system", "video", "fipe", "immobilizer", "advanced_functions", "scooter")
FORMAT_LABELS = {"LEGACY": "Formato legado — RESUMO MDL", "APPLICATION_GENERAL": "Nova base — APLICAÇÃO GERAL"}


class ScannerBaseAdapter(Protocol):
    format_name: str

    def parse(self, book, rules) -> ParsedBase: ...


def application_config():
    path = Path(
        os.environ.get(
            "MOTO_SCANNER_APPLICATION_CONFIG", Path(__file__).resolve().parents[1] / "config/scanner_application.json"
        )
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        set(data) != {"version", "min_year", "max_year"}
        or data["version"] != 1
        or any(type(data[k]) is not int for k in data)
    ):
        raise ValueError("Configuração do formato consolidado inválida")
    if not 1885 <= data["min_year"] <= data["max_year"] <= 2100:
        raise ValueError("Faixa de anos deve respeitar os limites do normalizador existente")
    return data


def application_header(row):
    return {
        column: APPLICATION_HEADERS[normalize_text(value).rstrip(".")]
        for column, value in row.items()
        if normalize_text(value).rstrip(".") in APPLICATION_HEADERS
    }


class LegacyScannerBaseAdapter:
    format_name = "LEGACY"

    def __init__(self, strict=False):
        self.strict = strict

    def parse(self, book, rules):
        tables = []
        for sheet in book.sheets:
            mapping = next(
                (header_map(row) for _, row in sheet.rows if REQUIRED <= set(header_map(row).values())), None
            )
            if mapping:
                if self.strict and not {"release", "situation"} & set(mapping.values()):
                    raise ValueError("Tabela sem colunas de situação ou lançamento")
                tables.append(sheet.name)
        if not tables:
            raise ValueError("Nenhuma aba contém a estrutura obrigatória")
        result = parse_workbook(book, rules)
        result.metadata = {"source_sheets": tables}
        return result


class ApplicationGeneralScannerBaseAdapter:
    format_name = "APPLICATION_GENERAL"

    def __init__(self, settings=None):
        self.settings = settings or application_config()

    def parse(self, book, rules):
        sheets = [s for s in book.sheets if normalize_text(s.name) == "APLICACAO GERAL"]
        if len(sheets) != 1:
            raise ValueError("Exige uma única aba consolidada APLICACAO GERAL")
        sheet = sheets[0]
        result = ParsedBase(source_format=self.format_name, metadata={"source_sheets": [sheet.name]})
        mapping = None
        fingerprints, application_keys = {}, {}
        errors = {int(re.search(r"\d+", cell)[0]) for cell in sheet.errors + sheet.formulas}
        for number, cells in sheet.rows:
            candidate = application_header(cells)
            if {"manufacturer", "model", "year", "system"} <= set(candidate.values()):
                if len(candidate) != len(set(candidate.values())):
                    raise ValueError("Cabeçalho duplicado na aba consolidada")
                missing = set(APPLICATION_HEADERS.values()) - set(candidate.values())
                if missing:
                    raise ValueError("Cabeçalhos ausentes na aba consolidada: " + ", ".join(sorted(missing)))
                if mapping is not None:
                    result.issues.append({"code": "REPEATED_HEADER", "sheet": sheet.name, "row": number})
                mapping = candidate
                continue
            if mapping is None:
                result.issues.append({"code": "OUTSIDE_TABLE", "sheet": sheet.name, "row": number, "raw": cells})
                continue
            fields = {name: cells.get(column, "") for column, name in mapping.items()}
            context = {"sheet": sheet.name, "row": number}
            try:
                if number in errors:
                    raise ValueError("Fórmula ou erro Excel na aplicação: requer valor explícito revisado")
                if any(not fields[k].strip() for k in REQUIRED):
                    raise ValueError("Fabricante, modelo, ano e sistema são obrigatórios")
                year = normalize_year(fields["year"])
                if not self.settings["min_year"] <= year <= self.settings["max_year"]:
                    raise ValueError("Ano fora da faixa configurada")
                manufacturer = normalize_manufacturer(fields["manufacturer"], rules["manufacturer_aliases"])
                model = " ".join(fields["model"].split())
                if not normalize_model(model):
                    raise ValueError("Modelo vazio após normalização")
                key = normalized_key(manufacturer, model, year)
            except ValueError as exc:
                result.rejected_rows += 1
                result.issues.append({**context, "code": "REJECTED_ROW", "detail": str(exc), "raw": cells})
                continue
            attrs = {}
            for field in ATTRIBUTES:
                raw = fields[field]
                normalized = normalize_text(raw)
                attrs[field] = {"SIM": "SIM", "NAO": "NÃO", "": None}.get(normalized)
                if normalized not in {"SIM", "NAO", ""}:
                    result.issues.append(
                        {**context, "code": "UNRECOGNIZED_ATTRIBUTE", "field": field, "raw_value": raw}
                    )
            application_key = (key, normalize_text(fields["system"]), normalize_text(fields["cable"]))
            fingerprint = tuple(sorted(fields.items()))
            duplicate = fingerprints.get(fingerprint)
            if duplicate is not None:
                result.issues.append({**context, "code": "DUPLICATE_ROW", "original_record_index": duplicate})
            else:
                fingerprints[fingerprint] = len(result.records)
            if application_key in application_keys and duplicate is None:
                result.issues.append(
                    {
                        **context,
                        "code": "APPLICATION_VARIANT",
                        "original_record_index": application_keys[application_key],
                        "detail": "Mesma identidade, sistema e cabo com atributos diferentes; ambos preservados.",
                    }
                )
            application_keys.setdefault(application_key, len(result.records))
            result.records.append(
                SystemRecord(
                    sheet=sheet.name,
                    row=number,
                    raw=dict(cells),
                    raw_fields=fields,
                    manufacturer=manufacturer,
                    model=model,
                    year=year,
                    key=key,
                    system=fields["system"].strip(),
                    system_key=application_key[1],
                    status="SEM_STATUS",
                    status_reason="Aplicação listada; não há regra documentada de suporte para este formato.",
                    release="",
                    date=None,
                    cable=fields["cable"],
                    cable_location="",
                    duplicate_of=duplicate,
                    source_format=self.format_name,
                    application_introduced_version=fields["application_introduced_version"] or None,
                    test_type=fields["test_type"] or None,
                    application_attributes=attrs,
                )
            )
        if mapping is None or not result.records:
            raise ValueError("Nenhuma aplicação válida na aba APLICACAO GERAL")
        result.sheets = [
            {
                "name": s.name,
                "populated_rows": len(s.rows),
                "dimension": s.dimension,
                "role": "primary" if s is sheet else "metadata",
                "formulas": len(s.formulas),
                "errors": len(s.errors),
            }
            for s in book.sheets
        ]
        self.complementary(book, result)
        return result

    def complementary(self, book, result):
        releases = []
        for sheet in book.sheets:
            name = normalize_text(sheet.name)
            if name.startswith("APLICACAO V"):
                versions = Counter()
                invalid = 0
                mapping = None
                for _, row in sheet.rows:
                    candidate = application_header(row)
                    if REQUIRED <= set(candidate.values()):
                        mapping = candidate
                        continue
                    if mapping:
                        fields = {field: row.get(col, "") for col, field in mapping.items()}
                        versions[fields.get("application_introduced_version", "")] += 1
                        try:
                            normalize_year(fields.get("year"))
                            if any(not fields.get(k) for k in REQUIRED):
                                raise ValueError("Estrutura incompleta")
                        except ValueError:
                            invalid += 1
                declared = name.split()[-1]
                inconsistent = any(v and normalize_text(v).removesuffix(".0") != declared for v in versions)
                releases.append(
                    {
                        "sheet": sheet.name,
                        "application_versions": dict(versions),
                        "invalid_rows": invalid,
                        "name_version_mismatch": inconsistent,
                    }
                )
                if inconsistent or invalid or sheet.formulas or sheet.errors:
                    result.issues.append(
                        {
                            "code": "COMPLEMENTARY_RELEASE_WARNING",
                            "sheet": sheet.name,
                            "detail": "Aba complementar não determina a versão oficial nem adiciona aplicações ao consolidado.",
                        }
                    )
            elif name == "VERSOES":
                summary = [{"row": n, "values": r} for n, r in sheet.rows]
                result.metadata["versions_summary"] = summary
                actual = {
                    "APLICACAO": len(result.records),
                    "SISTEMAS": len({r.system_key for r in result.records}),
                    "MONTADORA": len({r.manufacturer for r in result.records}),
                }
                comparisons = []
                for number, row in sheet.rows:
                    metric = normalize_text(row.get("A", ""))
                    candidates = [(col, value) for col, value in row.items() if col != "A" and value.isdigit()]
                    if metric in actual and candidates:
                        column, cached = candidates[-1]
                        comparisons.append(
                            {
                                "metric": metric,
                                "cell": f"{column}{number}",
                                "historical_cached": int(cached),
                                "consolidated": actual[metric],
                            }
                        )
                        if int(cached) != actual[metric]:
                            result.issues.append(
                                {
                                    "code": "SUMMARY_TOTAL_DIFFERS",
                                    "sheet": sheet.name,
                                    "row": number,
                                    "detail": f"{metric}: resumo histórico {cached}; consolidado {actual[metric]}. Escopos podem diferir; nenhuma correção automática.",
                                }
                            )
                result.metadata["summary_comparison"] = comparisons

                # Historical scope/cached formulas do not define the imported population.
                result.issues.append(
                    {
                        "code": "HISTORICAL_SUMMARY_NOT_AUTHORITATIVE",
                        "sheet": sheet.name,
                        "detail": "Resumo histórico com escopo próprio; os totais oficiais são calculados no consolidado. Valores em cache não são recalculados.",
                    }
                )
        result.metadata["complementary_releases"] = releases


def detect_adapter(book, strict_legacy=False) -> ScannerBaseAdapter:
    if any(normalize_text(s.name) == "APLICACAO GERAL" for s in book.sheets):
        return ApplicationGeneralScannerBaseAdapter()
    if any(
        "application_introduced_version" in application_header(row).values()
        for sheet in book.sheets
        for _, row in sheet.rows[:10]
    ):
        raise ValueError("Formato de aplicações exige a aba consolidada APLICACAO GERAL")
    return LegacyScannerBaseAdapter(strict_legacy)


def parse_scanner_workbook(book, rules, strict_legacy=False):
    return detect_adapter(book, strict_legacy).parse(book, rules)


def application_diagnostics(base):
    return {
        "format": base.source_format,
        "format_label": FORMAT_LABELS[base.source_format],
        "applications": len(base.records),
        "unique_applications": sum(r.duplicate_of is None for r in base.records),
        "application_keys": len({(r.key, r.system_key, normalize_text(r.cable)) for r in base.records}),
        "unique_systems": len({r.system_key for r in base.records}),
        "metadata": base.metadata,
    }
