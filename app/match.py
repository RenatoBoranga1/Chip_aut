import argparse
import json
import logging
from pathlib import Path

from matching.models import MotorcycleQuery
from matching.rules import DEFAULT_MATCHING_RULES
from services.matching_service import match_motorcycle


def main():
    parser = argparse.ArgumentParser(description="Comparar uma moto com a última base importada")
    parser.add_argument("--manufacturer", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--year", help="Ano exato; ausente ou ambíguo exige revisão")
    parser.add_argument("--version", default="")
    parser.add_argument("--db", type=Path, default=Path("data/coverage.sqlite3"))
    parser.add_argument("--rules", type=Path, default=DEFAULT_MATCHING_RULES)
    parser.add_argument("--reports", type=Path, default=Path("reports/matching"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        saved = match_motorcycle(
            MotorcycleQuery(args.manufacturer, args.model, args.year, args.version), args.db, args.rules
        )
        args.reports.mkdir(parents=True, exist_ok=True)
        output = args.reports / f"match-{saved['run_id']:04d}.json"
        output.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(saved, ensure_ascii=False, indent=2))
        print(f"Relatório: {output.resolve()}")
    except Exception:
        logging.getLogger(__name__).exception("matching_failed")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
