import re
from datetime import datetime

from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900, from_excel

from scanner_base.excel_reader import WorkbookData
from scanner_base.models import ParsedBase, SystemRecord
from scanner_base.normalizer import (
    normalize_manufacturer,
    normalize_model,
    normalize_text,
    normalize_year,
    normalized_key,
)
from scanner_base.status import classify

HEADERS = {
    "LANC": "release",
    "DATA": "date",
    "MONTADORA": "manufacturer",
    "MODELO": "model",
    "ANO": "year",
    "SISTEMA": "system",
    "CABO": "cable",
    "LOCALIZACAO CABO": "cable_location",
    "SIT": "situation",
}
REQUIRED = {"manufacturer", "model", "year", "system"}


def header_map(row):
    return {
        col: HEADERS[normalize_text(value).rstrip(".")]
        for col, value in row.items()
        if normalize_text(value).rstrip(".") in HEADERS
    }


def parse_date(value: str, date1904: bool) -> str | None:
    if not value.strip():
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
        epoch = CALENDAR_MAC_1904 if date1904 else CALENDAR_WINDOWS_1900
        result = from_excel(float(value), epoch)
        if not isinstance(result, datetime):
            raise ValueError("Serial sem data")
        return result.date().isoformat()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {value!r}")


def parse_workbook(book: WorkbookData, rules: dict) -> ParsedBase:
    result = ParsedBase()
    found = False
    fingerprints = {}
    for sheet in book.sheets:
        metadata = {
            "name": sheet.name,
            "dimension": sheet.dimension,
            "populated_rows": len(sheet.rows),
            "columns": [],
            "header_row": None,
        }
        result.sheets.append(metadata)
        mapping = None
        error_rows = {int(re.search(r"\d+", c).group()) for c in sheet.errors + sheet.formulas}
        for number, cells in sheet.rows:
            candidate = header_map(cells)
            if REQUIRED <= set(candidate.values()):
                if len(candidate) != len(set(candidate.values())):
                    raise ValueError(f"Cabeçalho duplicado em {sheet.name}, linha {number}")
                if mapping is not None:
                    result.issues.append({"sheet": sheet.name, "row": number, "code": "REPEATED_HEADER"})
                mapping = candidate
                found = True
                metadata["header_row"] = metadata["header_row"] or number
                metadata["columns"] = list(cells.values())
                continue
            if mapping is None:
                result.issues.append({"sheet": sheet.name, "row": number, "code": "OUTSIDE_TABLE", "raw": cells})
                continue
            fields = {name: cells.get(col, "") for col, name in mapping.items()}
            issue_base = {"sheet": sheet.name, "row": number}
            try:
                if number in error_rows:
                    raise ValueError("Fórmula ou erro Excel: requer valor explícito revisado")
                missing = [name for name in REQUIRED if not fields.get(name, "").strip()]
                if missing:
                    raise ValueError(f"Campos obrigatórios vazios: {', '.join(sorted(missing))}")
                year = normalize_year(fields["year"])
                manufacturer = normalize_manufacturer(fields["manufacturer"], rules["manufacturer_aliases"])
                model = " ".join(fields["model"].split())
                if not normalize_model(model):
                    raise ValueError("Modelo vazio após normalização")
                key = normalized_key(manufacturer, model, year)
            except ValueError as exc:
                result.rejected_rows += 1
                result.issues.append({**issue_base, "code": "REJECTED_ROW", "detail": str(exc), "raw": cells})
                continue
            date = None
            try:
                date = parse_date(fields.get("date", ""), book.date1904)
            except (ValueError, OverflowError) as exc:
                result.issues.append({**issue_base, "code": "INVALID_DATE", "detail": str(exc)})
            status, reason = classify(fields.get("release", ""), fields.get("situation", ""), rules)
            if status == "SEM_STATUS":
                result.issues.append({**issue_base, "code": "UNRESOLVED_STATUS", "detail": reason})
            raw = dict(cells)
            fingerprint = tuple(sorted(fields.items()))
            duplicate = fingerprints.get(fingerprint)
            if duplicate is not None:
                original = result.records[duplicate]
                result.issues.append(
                    {
                        **issue_base,
                        "code": "DUPLICATE_ROW",
                        "original_record_index": duplicate,
                        "original_sheet": original.sheet,
                        "original_row": original.row,
                    }
                )
            else:
                fingerprints[fingerprint] = len(result.records)
            result.records.append(
                SystemRecord(
                    sheet.name,
                    number,
                    raw,
                    fields,
                    manufacturer,
                    model,
                    year,
                    key,
                    fields["system"].strip(),
                    normalize_text(fields["system"]),
                    status,
                    reason,
                    fields.get("release", ""),
                    date,
                    fields.get("cable", ""),
                    fields.get("cable_location", ""),
                    duplicate,
                )
            )
        if mapping is None:
            result.issues.append({"sheet": sheet.name, "code": "IGNORED_SHEET", "detail": "Sem cabeçalho reconhecido"})
    if not found or not result.records:
        raise ValueError("Nenhum registro válido com MONTADORA, MODELO, ANO e SISTEMA")
    return result
