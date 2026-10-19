"""Inspect the registry without collecting or modifying the database."""

import argparse
import json
import os
import sys
from dataclasses import asdict

from partners.assessments import unintegrated
from partners.diagnostics import diagnose
from partners.registry import PartnerRegistry
from partners.sources import dry_run, source_report
from services.partner_service import partner_status


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "inbox":
        from app.partner_inbox import main as inbox_main

        return inbox_main(argv[1:])
    parser = argparse.ArgumentParser(description="Parceiros configurados")
    parser.add_argument(
        "command",
        choices=["list", "status", "show", "diagnose", "sources", "collect", "import", "triage", "stage", "auth"],
    )
    parser.add_argument("partner", nargs="?")
    parser.add_argument("file", nargs="?")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--authorized", action="store_true")
    parser.add_argument("--motorcycles", action="store_true")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--mapping", type=str)
    parser.add_argument("--mode", choices=["INCREMENTAL", "FULL_SNAPSHOT"], default="INCREMENTAL")
    parser.add_argument("--id")
    parser.add_argument("--classification", choices=["MOTORCYCLE", "KART", "SERVICE", "OTHER", "UNKNOWN"])
    parser.add_argument("--revision", type=int)
    parser.add_argument("--note", default="")
    parser.add_argument("--identity", help="JSON com marca/modelo/ano confirmados")
    parser.add_argument("--db", default=os.environ.get("MOTO_DB", "data/coverage.sqlite3"))
    parser.add_argument("--live", action="store_true", help="Diagnóstico HTTP limitado, sem salvar anúncios")
    parser.add_argument("--dry-run", action="store_true", help="Diagnóstico sem persistência")
    args = parser.parse_args(argv)
    if args.dry_run and args.command not in {"collect", "import", "stage", "auth"}:
        parser.error("--dry-run somente pode ser usado com collect")
    if args.command == "collect" and not args.dry_run:
        parser.error("Fontes alternativas permitem somente collect --dry-run")
    if args.live and args.command != "diagnose":
        parser.error("--live somente pode ser usado com diagnose")
    try:
        registry = PartnerRegistry()
        if args.command == "import":
            from pathlib import Path

            from services.partner_inventory_import import PartnerInventoryImportService

            if not args.partner or not args.file:
                parser.error("import exige parceiro e arquivo")
            path = Path(args.file)
            mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else None
            service = PartnerInventoryImportService(args.db)
            if args.dry_run:
                output = service.preview(args.partner, path.read_bytes(), path.name, mapping=mapping, mode=args.mode)
            else:
                output = service.confirm(
                    args.partner,
                    path.read_bytes(),
                    path.name,
                    mapping=mapping,
                    mode=args.mode,
                    confirmed=args.confirm,
                    authorized=args.authorized,
                    motorcycles_confirmed=args.motorcycles,
                    reviewer=args.reviewer,
                )
        elif args.command in {"triage", "stage"}:
            from database.inventory_repository import read_operations
            from services.motonil_staging_service import MotonilStagingService

            if args.partner != "motonil":
                parser.error("Triagem disponível somente para Motonil")
            service = MotonilStagingService(args.db)
            if args.command == "stage":
                output = diagnose("motonil", live=True) if args.dry_run else service.collect()
            elif args.classification:
                if not args.confirm:
                    parser.error("Classificação exige --confirm")
                output = service.classify(
                    args.id,
                    args.classification,
                    reviewer=args.reviewer,
                    note=args.note,
                    expected_revision=args.revision,
                    identity=json.loads(args.identity) if args.identity else None,
                )
            else:
                output = read_operations(args.db)["staging"]
        elif args.command == "auth":
            from partners.authenticated_source import AuthenticatedSource, collect_authenticated

            if args.partner != "thomas_motos":
                parser.error("Fonte autenticada disponível somente para Thomas")
            output = (
                AuthenticatedSource().read()
                if args.dry_run
                else collect_authenticated(args.db, confirmed=args.confirm, reviewer=args.reviewer)
            )
        elif args.command in {"sources", "collect"}:
            if not args.partner:
                parser.error("Informe a chave do parceiro")
            output = source_report(args.partner) if args.command == "sources" else dry_run(args.partner)
        elif args.command == "diagnose":
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
            from database.inventory_repository import read_operations

            operational = {p["partner_key"]: p for p in read_operations(args.db)["partners"]}
            output = [
                {**row, **operational.get(row["partner"], {})}
                for row in partner_status(args.db, registry, include_candidates=True)
            ]
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
