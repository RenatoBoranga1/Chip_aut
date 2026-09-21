import argparse
import json
from pathlib import Path

from matching.rules import DEFAULT_MATCHING_RULES
from services.refinement_service import analyze_refinement


def main():
    parser = argparse.ArgumentParser(description="Auditar refinamento offline contra uma cobertura anterior")
    parser.add_argument("collection_id", type=int)
    parser.add_argument("--baseline-coverage", required=True, type=int)
    parser.add_argument("--db", type=Path, default=Path("data/coverage.sqlite3"))
    parser.add_argument("--reports", type=Path, default=Path("reports/refinement"))
    parser.add_argument("--rules", type=Path, default=DEFAULT_MATCHING_RULES)
    args = parser.parse_args()
    report = analyze_refinement(args.collection_id, args.baseline_coverage, args.db, args.reports, args.rules)
    print(json.dumps({k: v for k, v in report.items() if k != "policy"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
