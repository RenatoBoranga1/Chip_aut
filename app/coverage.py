import argparse
import json
from pathlib import Path

from services.coverage_service import build_coverage


def main():
    parser = argparse.ArgumentParser(description="Comparar uma coleta persistida com a base vigente")
    parser.add_argument("collection_id", type=int)
    parser.add_argument("--db", type=Path, default=Path("data/coverage.sqlite3"))
    parser.add_argument("--reports", type=Path, default=Path("reports/coverage"))
    parser.add_argument(
        "--automatic-only", action="store_true", help="Auditoria histórica sem projetar decisões ou atualizar fila"
    )
    args = parser.parse_args()
    report = build_coverage(
        args.collection_id,
        args.db,
        args.reports / f"collection-{args.collection_id:04d}",
        update_queue=not args.automatic_only,
    )
    print(json.dumps({k: v for k, v in report.items() if k != "groups"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
