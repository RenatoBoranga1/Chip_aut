import json
import logging
import time
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from database.repository import SQLiteRepository
from scanner_base.aggregator import consolidate
from scanner_base.excel_reader import read_excel
from scanner_base.normalizer import normalize_text
from scanner_base.parser import parse_workbook
from scanner_base.status import STATUSES

LOGGER = logging.getLogger(__name__)
DEFAULT_RULES = Path(__file__).resolve().parents[1] / "config" / "rules.json"


def file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_rules(path=DEFAULT_RULES):
    rules = json.loads(Path(path).read_text(encoding="utf-8"))
    for field in ("release_status", "situation_status"):
        if not isinstance(rules.get(field), dict) or not set(rules[field].values()) <= STATUSES - {"SUPORTE_PARCIAL"}:
            raise ValueError(f"Mapeamento de status inválido: {field}")
        rules[field] = {normalize_text(k): v for k, v in rules[field].items()}
    rules["manufacturer_aliases"] = {
        normalize_text(k): normalize_text(v) for k, v in rules["manufacturer_aliases"].items()
    }
    return rules


def import_base(source: Path, database: Path, rules_path: Path = DEFAULT_RULES):
    started = time.perf_counter()
    LOGGER.info(json.dumps({"event": "import_started", "source": str(source)}))
    rules = load_rules(rules_path)
    before = file_digest(source)
    book = read_excel(source)
    base = parse_workbook(book, rules)
    consolidate(base)
    after = file_digest(source)
    if before != after:
        raise ValueError("O arquivo mudou durante a leitura; repita a importação")
    variants = {}
    for record in base.records:
        variants.setdefault(record.manufacturer, set()).add(record.raw_fields["manufacturer"])
    report = {
        "source": str(source.resolve()),
        "sha256": before,
        "source_unchanged": True,
        "sheets": base.sheets,
        "valid_system_records": len(base.records),
        "raw_unique_motorcycles": len(
            {(r.raw_fields["manufacturer"], r.raw_fields["model"], r.raw_fields["year"]) for r in base.records}
        ),
        "unique_motorcycles": len(base.motorcycles),
        "rejected_rows": base.rejected_rows,
        "exact_duplicate_rows": sum(r.duplicate_of is not None for r in base.records),
        "unique_motorcycle_systems": sum(m.system_count for m in base.motorcycles),
        "manufacturers": dict(sorted(Counter(m.manufacturer for m in base.motorcycles).items())),
        "manufacturer_variants": {k: sorted(v) for k, v in sorted(variants.items())},
        "motorcycle_statuses": dict(Counter(m.status for m in base.motorcycles)),
        "record_statuses": dict(Counter(r.status for r in base.records)),
        "issues_by_code": dict(Counter(i["code"] for i in base.issues)),
        "release_values": dict(Counter(r.release for r in base.records)),
        "earliest_date": min((r.date for r in base.records if r.date), default=None),
        "latest_date": max((r.date for r in base.records if r.date), default=None),
        "policy": rules,
        "examples": [asdict(m) for m in base.motorcycles[:8]],
        "processing_seconds": round(time.perf_counter() - started, 3),
    }
    with SQLiteRepository(database) as repository:
        import_id, diff = repository.save_import(base, str(source.resolve()), before, rules, report)
    report.update(import_id=import_id, diff=diff)
    LOGGER.info(
        json.dumps(
            {
                "event": "import_completed",
                "id": import_id,
                "records": len(base.records),
                "motorcycles": len(base.motorcycles),
                "seconds": round(time.perf_counter() - started, 3),
            }
        )
    )
    return base, report
