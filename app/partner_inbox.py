"""Explicit inbox commands; scan/validate never publish inventory."""

import argparse
import json
import os
from pathlib import Path

from database.inbox_repository import read_inbox
from services.partner_inbox_service import PartnerInboxService


def main(argv=None):
    parser = argparse.ArgumentParser(description="Caixa de entrada dos parceiros")
    parser.add_argument("command", choices=["scan", "list", "show", "validate", "confirm", "reject"])
    parser.add_argument("id", type=int, nargs="?")
    parser.add_argument("--partner", choices=["thomas_motos", "moto_marques"])
    parser.add_argument("--db", default=os.environ.get("MOTO_DB", "data/coverage.sqlite3"))
    parser.add_argument("--mode", choices=["INCREMENTAL", "FULL_SNAPSHOT"], default="INCREMENTAL")
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--revision", type=int)
    parser.add_argument("--preview-hash")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--authorized", action="store_true")
    parser.add_argument("--motorcycles", action="store_true")
    parser.add_argument("--accept-anomalies", action="store_true")
    args = parser.parse_args(argv)
    try:
        service = PartnerInboxService(args.db)
        if args.command == "scan":
            output = service.scan(args.partner)
        elif args.command == "list":
            output = read_inbox(args.db, args.partner)
        else:
            if args.id is None:
                parser.error("Informe a referência do arquivo")
            if args.command in {"confirm", "reject", "validate"} and args.revision is None:
                parser.error("Informe --revision da revisão exibida")
            if args.command == "show":
                output = service.get(args.id)
            elif args.command == "validate":
                mapping = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping else None
                output = service.validate(args.id, expected_revision=args.revision, mapping=mapping, mode=args.mode)
            elif args.command == "reject":
                output = service.reject(
                    args.id,
                    expected_revision=args.revision,
                    reviewer=args.reviewer,
                    reason=args.reason,
                    confirmed=args.confirm,
                )
            else:
                output = service.confirm(
                    args.id,
                    expected_revision=args.revision,
                    preview_hash=args.preview_hash,
                    reviewer=args.reviewer,
                    confirmed=args.confirm,
                    authorized=args.authorized,
                    motorcycles_confirmed=args.motorcycles,
                    accept_anomalies=args.accept_anomalies,
                )
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, TypeError) as exc:
        print("Não foi possível concluir a operação da inbox: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
