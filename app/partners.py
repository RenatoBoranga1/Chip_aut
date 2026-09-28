"""Inspect the registry without collecting or modifying the database."""

import argparse
import json
import os
from dataclasses import asdict

from partners.registry import PartnerRegistry
from services.partner_service import partner_status


def main(argv=None):
    parser = argparse.ArgumentParser(description="Parceiros configurados")
    parser.add_argument("command", choices=["list", "status", "show"])
    parser.add_argument("partner", nargs="?")
    parser.add_argument("--db", default=os.environ.get("MOTO_DB", "data/coverage.sqlite3"))
    args = parser.parse_args(argv)
    try:
        registry = PartnerRegistry()
        if args.command == "show":
            if not args.partner:
                parser.error("show exige a chave do parceiro")
            output = asdict(registry.get(args.partner))
        elif args.command == "status":
            output = partner_status(args.db, registry)
        else:
            output = [{"partner": p.partner_key, "name": p.display_name, "enabled": p.enabled} for p in registry.list()]
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, TypeError, OSError) as exc:
        print(f"Não foi possível consultar parceiros: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
