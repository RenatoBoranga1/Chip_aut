"""Untrusted XLSX validation; reuse the sparse OOXML reader and scanner rules."""

import hashlib
import io
import json
import os
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from xml.etree.ElementTree import ParseError
from xml.parsers.expat import ExpatError
from zipfile import BadZipFile, ZipFile

from scanner_base.aggregator import consolidate
from scanner_base.excel_reader import read_excel
from scanner_base.models import Motorcycle, ParsedBase, SystemRecord
from scanner_base.parser import REQUIRED, header_map, parse_workbook
from services.import_service import load_rules


def config():
    path = Path(
        os.environ.get("MOTO_SCANNER_IMPORT_CONFIG", Path(__file__).resolve().parents[1] / "config/scanner_import.json")
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "version",
        "enabled",
        "max_upload_mb",
        "require_confirmation",
        "preserve_original",
        "detect_duplicates",
        "revalidate_human_decisions",
        "auto_publish",
    }
    if set(data) != expected or type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("Configuração de importação incompatível")
    if type(data["max_upload_mb"]) not in (int, float) or not 0 < data["max_upload_mb"] <= 100:
        raise ValueError("Limite de upload inválido")
    if any(type(data[k]) is not bool for k in expected - {"version", "max_upload_mb"}):
        raise ValueError("Opções de importação inválidas")
    if (
        any(
            not data[k]
            for k in ("require_confirmation", "preserve_original", "detect_duplicates", "revalidate_human_decisions")
        )
        or data["auto_publish"]
    ):
        raise ValueError("As proteções obrigatórias da publicação não podem ser desabilitadas")
    return data


def unpack(payload):
    return ParsedBase(
        records=[SystemRecord(**r) for r in payload["records"]],
        motorcycles=[Motorcycle(**m) for m in payload["motorcycles"]],
        issues=payload["issues"],
        sheets=payload["sheets"],
        rejected_rows=payload["rejected_rows"],
    )


def validate_upload(content, filename, settings=None):
    started = time.perf_counter()
    settings = settings or config()
    if not isinstance(filename, str) or Path(filename).suffix.lower() != ".xlsx":
        raise ValueError("Envie um arquivo .xlsx")
    if not content or len(content) > settings["max_upload_mb"] * 1024 * 1024:
        raise ValueError("Arquivo vazio ou maior que o limite configurado")
    if not content.startswith(b"PK\x03\x04"):
        raise ValueError("Assinatura inválida: o arquivo não é um XLSX")
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            names = [i.filename for i in entries]
            if (
                len(entries) > 10000
                or len(names) != len(set(names))
                or sum(i.file_size for i in entries) > 512 * 1024 * 1024
            ):
                raise ValueError("Conteúdo compactado excede limites ou contém entradas duplicadas")
            if any(".." in n.replace("\\", "/").split("/") or n.startswith(("/", "\\")) for n in names):
                raise ValueError("Estrutura interna inválida")
            if not {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"} <= set(names):
                raise ValueError("Estrutura XLSX incompleta")
            if any("vbaproject" in n.lower() or n.lower().startswith("xl/externallinks/") for n in names):
                raise ValueError("Macros e vínculos externos não são aceitos")
            if b"macroenabled" in archive.read("[Content_Types].xml").lower():
                raise ValueError("Macros não são aceitas")
            if archive.testzip():
                raise ValueError("Arquivo corrompido")
        book = read_excel(io.BytesIO(content))
        tables = []
        for sheet in book.sheets:
            mapping = next(
                (header_map(row) for _, row in sheet.rows if REQUIRED <= set(header_map(row).values())), None
            )
            if mapping:
                if not {"release", "situation"} & set(mapping.values()):
                    raise ValueError("Tabela sem colunas de situação ou lançamento")
                tables.append(sheet.name)
        if not tables:
            raise ValueError("Nenhuma aba contém a estrutura obrigatória")
        rules = load_rules()
        base = parse_workbook(book, rules)
        consolidate(base)
    except (BadZipFile, KeyError, IndexError, OverflowError, ParseError, ExpatError) as exc:
        raise ValueError("Arquivo corrompido ou estrutura de planilha inválida") from exc
    counts = Counter(i["code"] for i in base.issues)
    report = {
        "total_records": len(base.records) + base.rejected_rows,
        "valid_records": len(base.records),
        "unique_vehicles": len(base.motorcycles),
        "invalid_records": base.rejected_rows,
        "duplicates": counts["DUPLICATE_ROW"],
        "conflicts": counts["CONFLICTING_SYSTEM"],
        "invalid_dates": counts["INVALID_DATE"],
        "issues": dict(counts),
        "sheets": tables,
        "seconds": round(time.perf_counter() - started, 4),
    }
    report["publishable"] = not (base.rejected_rows or counts["INVALID_DATE"])
    return base, rules, report, hashlib.sha256(content).hexdigest()


def comparable_records(records):
    # Keep raw support columns (including undocumented codes), but ignore sheet/row order.
    result = {}
    for record in records:
        r = asdict(record) if isinstance(record, SystemRecord) else record
        fields = r["raw_fields"]
        support = {k: v for k, v in fields.items() if k not in {"manufacturer", "model", "year"}}
        extra = sorted(v for col, v in r["raw"].items() if v not in fields.values())
        result.setdefault(r["key"], set()).add(json.dumps([support, extra], sort_keys=True, ensure_ascii=False))
    return {k: sorted(v) for k, v in result.items()}


def differences(old, new, old_records, new_records):
    before, after = set(old), set(new)
    details = []
    same = 0
    support_old, support_new = comparable_records(old_records), comparable_records(new_records)
    for key in sorted(before | after):
        a, b = old.get(key), new.get(key)
        if a is None:
            kind = "ADDED"
        elif b is None:
            kind = "REMOVED"
        else:
            changed = [f for f in a if f not in {"record_count"} and a.get(f) != b.get(f)]
            if support_old.get(key) != support_new.get(key):
                changed.append("support_fields")
            if not changed:
                same += 1
                continue
            kind = "CHANGED"
        row = {
            "key": key,
            "before": a,
            "after": b,
            "fields": changed if a and b else [],
            "support_before": support_old.get(key, []),
            "support_after": support_new.get(key, []),
        }
        details.append((kind, key, row))
    # A removed/added identity sharing brand/year is only a review hint, never a merge.
    removed_groups = {(old[k]["manufacturer"], old[k]["year"]) for k in before - after}
    pending = [k for k in after - before if (new[k]["manufacturer"], new[k]["year"]) in removed_groups]
    for key in pending:
        details.append(
            (
                "IDENTITY_REVIEW",
                key,
                {"key": key, "message": "Comparação pendente de revisão; nenhuma identidade foi unida"},
            )
        )
    counts = Counter(kind for kind, _, _ in details)
    return {
        "previous": len(old),
        "new": len(new),
        "added": counts["ADDED"],
        "removed": counts["REMOVED"],
        "changed": counts["CHANGED"],
        "unchanged": same,
        "identity_review": len(pending),
    }, details
