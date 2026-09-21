import argparse
import logging
from pathlib import Path

from services.import_service import DEFAULT_RULES, import_base
from services.report_service import write_reports


def main():
    parser = argparse.ArgumentParser(description="Importar e consolidar base scanner sem alterar o Excel")
    parser.add_argument("file", type=Path)
    parser.add_argument("--db", type=Path, default=Path("data/coverage.sqlite3"))
    parser.add_argument("--reports", type=Path, default=Path("reports"))
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        base, report = import_base(args.file, args.db, args.rules)
        destination = args.reports / f"import-{report['import_id']:04d}"
        write_reports(base, report, destination)
    except Exception:
        logging.getLogger(__name__).exception("import_failed")
        raise SystemExit(1) from None
    print(
        f"Importação {report['import_id']}: {len(base.records)} registros; "
        f"{len(base.motorcycles)} veículos. Relatórios: {destination.resolve()}"
    )


if __name__ == "__main__":
    main()
