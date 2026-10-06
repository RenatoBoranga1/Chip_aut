"""Inspect the registry without collecting or modifying the database."""

import argparse
import json
import os
from dataclasses import asdict

from partners.assessments import unintegrated
from partners.diagnostics import diagnose
from partners.registry import PartnerRegistry
from services.partner_service import partner_status


def main(argv=None):
    parser = argparse.ArgumentParser(description="Parceiros configurados")
    parser.add_argument("command", choices=["list", "status", "show", "diagnose"])
    parser.add_argument("partner", nargs="?")
    parser.add_argument("--db", default=os.environ.get("MOTO_DB", "data/coverage.sqlite3"))
    parser.add_argument("--live", action="store_true", help="Diagnóstico HTTP limitado, sem salvar anúncios")
    args = parser.parse_args(argv)
    if args.live and args.command != "diagnose":
        parser.error("--live somente pode ser usado com diagnose")
    try:
        registry = PartnerRegistry()
        if args.command == "diagnose":
            if not args.partner:
                parser.error("diagnose exige a chave do parceiro")
            output = diagnose(args.partner, live=args.live)
        elif args.command == "show":
            if not args.partner:
                parser.error("show exige a chave do parceiro")
            candidate = next((p for p in unintegrated(registry) if p["partner"] == args.partner), None)
            if candidate:
                output = candidate
            else:
                entry = registry.get(args.partner)
                output = {**asdict(entry), "integration_status": "Ativo" if entry.enabled else "Desabilitado"}
        elif args.command == "status":
            output = partner_status(args.db, registry, include_candidates=True)
        else:
            output = [
                {
                    "partner": p.partner_key,
                    "name": p.display_name,
                    "enabled": p.enabled,
                    "integration_status": "Ativo" if p.enabled else "Desabilitado",
                }
                for p in registry.list()
            ] + unintegrated(registry)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, TypeError, OSError) as exc:
        print(f"Não foi possível consultar parceiros: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
