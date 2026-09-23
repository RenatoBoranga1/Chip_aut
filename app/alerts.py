"""Retry pending internal alerts without collecting or changing coverage."""

import argparse
import os
from pathlib import Path

from database.alert_repository import read_alerts
from services.alert_service import process_pending
from services.pipeline_lock import ExecutionLock


def main():
    parser = argparse.ArgumentParser(description="Processar alertas pendentes")
    parser.add_argument("--db", default=os.environ.get("MOTO_DB", "data/coverage.sqlite3"))
    args = parser.parse_args()
    if not Path(args.db).is_file():
        parser.error("Banco não encontrado; informe o banco operacional existente")
    with ExecutionLock(args.db):
        process_pending(args.db)
    pending = read_alerts(args.db)["pending"]
    print(f"Entregas pendentes: {pending}")
    return 1 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
