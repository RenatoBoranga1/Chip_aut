"""Explicit evaluation and read-only simulation of operational priority."""

import argparse
import json
import os
from pathlib import Path

from services.dashboard_service import DashboardConfig
from services.prioritization_policy import load_policy
from services.prioritization_service import PrioritizationService


def main(argv=None):
    parser = argparse.ArgumentParser(description="Priorização operacional explicável")
    parser.add_argument("command", choices=["refresh", "list", "simulate"])
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("MOTO_DB", "data/coverage.sqlite3")))
    parser.add_argument("--partner", default="wr_motos")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--read-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        readonly = args.read_only or os.environ.get("MOTO_READ_ONLY", "0").lower() in {"1", "true", "yes"}
        service = PrioritizationService(DashboardConfig(args.db, args.partner, readonly))
        if args.command == "refresh":
            result = service.refresh("cli")
        elif args.command == "simulate":
            if not args.policy:
                parser.error("Informe --policy para simulação")
            result = service.simulate(load_policy(args.policy))
        else:
            result = service.listing()
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"Não foi possível executar: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
