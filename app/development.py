"""Local administration of explicitly confirmed development needs."""

import argparse
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from database.repository import SQLiteRepository
from services.dashboard_service import DashboardConfig
from services.development_alerts import scan_stale
from services.development_policy import PRIORITIES, REASONS, STATES
from services.development_service import DevelopmentService


def main():
    parser = argparse.ArgumentParser(description="Gestão de motos para desenvolvimento; não altera a base do scanner")
    parser.add_argument("--db", type=Path, default=Path("data/coverage.sqlite3"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--read-only", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Aplicar migrations aditivas")
    commands.add_parser("scan", help="Verificar prazos e emitir avisos internos")
    listing = commands.add_parser("list")
    listing.add_argument("--status", type=str.upper, choices=STATES)
    listing.add_argument("--page", type=int, default=0)
    show = commands.add_parser("show")
    show.add_argument("id", type=int)
    show.add_argument("--page", type=int, default=0)
    create = commands.add_parser("create")
    create.add_argument("--source", choices=["review", "alert", "advertisement", "scanner"], required=True)
    create.add_argument("--id", required=True)
    create.add_argument("--partner", default="wr_motos")
    create.add_argument("--reason", type=str.upper, choices=REASONS, required=True)
    create.add_argument("--confirm", action="store_true")
    create.add_argument("--priority", choices=PRIORITIES)
    for name in ["status", "priority", "assign", "note", "technical", "checklist"]:
        sub = commands.add_parser(name)
        sub.add_argument("id", type=int)
        sub.add_argument(
            "--to" if name in {"status", "priority", "assign"} else "--text" if name == "note" else "--data",
            dest="value",
            required=True,
        )
        sub.add_argument("--revision", type=int, required=True)
        if name == "status":
            sub.add_argument("--base-version")
    for name, sub in commands.choices.items():
        if name not in {"init", "scan", "list", "show"}:
            sub.add_argument("--actor", required=True)
            sub.add_argument("--justification", required=True)
            sub.add_argument("--request-key", default=None)
    args = parser.parse_args()
    config = replace(DashboardConfig.from_env(), database=args.db, partner=getattr(args, "partner", "wr_motos"))
    config = replace(config, read_only=args.read_only or config.read_only)
    try:
        service = DevelopmentService(config)
        if args.command == "list":
            result = service.listing(filters={"status": [args.status]} if args.status else {}, page=args.page)
        elif args.command == "show":
            result = service.detail(args.id, args.page)
        elif args.command == "init":
            service.writable()
            with SQLiteRepository(args.db):
                pass
            result = {"mensagem": "Gestão de desenvolvimento inicializada"}
        elif args.command == "scan":
            service.writable()
            result = {"avisos_criados": scan_stale(args.db, service.policy, force=True)}
        else:
            common = {
                "actor": args.actor,
                "justification": args.justification,
                "command_key": args.request_key or str(uuid4()),
            }
            if args.command == "create":
                item_id = service.create(
                    args.source, args.id, reason=args.reason, priority=args.priority, confirmed=args.confirm, **common
                )
            else:
                value = (
                    json.loads(args.value)
                    if args.command in {"technical", "checklist"}
                    else args.value.upper()
                    if args.command == "status"
                    else args.value
                )
                item_id = service.change(
                    args.id,
                    "assigned_to" if args.command == "assign" else args.command,
                    value,
                    expected_revision=args.revision,
                    completion_version=getattr(args, "base_version", None),
                    **common,
                )
            result = {"item": item_id, "mensagem": "Operação registrada"}
        if args.json:
            print(json.dumps(result, ensure_ascii=True, default=str))
        elif args.command == "list":
            for item in result["items"]:
                print(
                    f"{item['id']} · {item['manufacturer']} {item['model']} · {STATES[item['status']]} · {PRIORITIES[item['priority']]} · {item['assigned_to'] or 'Sem responsável'}"
                )
            print(f"{result['total']} itens")
        elif args.command == "show":
            print(
                f"Item {result['id']} · {result['manufacturer']} {result['model']} · {STATES[result['status']]} · revisão {result['revision']}"
            )
            print("Use --json para consultar todos os campos e o histórico paginado.")
        else:
            print(result)
    except (ValueError, OSError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    main()
