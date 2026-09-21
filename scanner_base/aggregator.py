from collections import defaultdict

from scanner_base.models import Motorcycle, ParsedBase
from scanner_base.normalizer import normalize_model
from scanner_base.status import aggregate_status


def consolidate(base: ParsedBase) -> None:
    grouped = defaultdict(list)
    for record in base.records:
        grouped[record.key].append(record)
    motorcycles = []
    for key, records in sorted(grouped.items()):
        systems = defaultdict(list)
        for record in records:
            if record.duplicate_of is None:
                systems[record.system_key].append(record)
        by_status = defaultdict(list)
        for system_key, observations in sorted(systems.items()):
            values = {r.status for r in observations}
            status = next(iter(values)) if len(values) == 1 else "SEM_STATUS"
            if len(values) > 1:
                base.issues.append(
                    {
                        "code": "CONFLICTING_SYSTEM",
                        "key": key,
                        "system": system_key,
                        "rows": [r.row for r in observations],
                    }
                )
            by_status[status].append(observations[0].system)
        first = records[0]
        dates = [r.date for r in records if r.date]
        motorcycles.append(
            Motorcycle(
                key,
                first.manufacturer,
                first.model,
                first.year,
                normalize_model(first.model),
                aggregate_status(list(by_status)),
                len(systems),
                len(records),
                by_status["SUPORTADO"],
                by_status["SEM_SUPORTE"],
                by_status["EM_ANALISE"],
                by_status["SEM_STATUS"],
                max(dates) if dates else None,
                sorted({r.release for r in records if r.release}),
            )
        )
    base.motorcycles = motorcycles
