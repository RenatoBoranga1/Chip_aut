"""Administrative scanner update workflow; publication always explicitly confirmed."""

import argparse
import json
import os
from pathlib import Path

from services.scanner_service import ScannerService


def main(argv=None):
    p = argparse.ArgumentParser(description="Atualização segura da base do scanner")
    p.add_argument("command", choices=["list", "current", "validate", "compare", "show", "publish", "resume"])
    p.add_argument("file", nargs="?")
    p.add_argument("--db", type=Path, default=Path(os.environ.get("MOTO_DB", "data/coverage.sqlite3")))
    p.add_argument("--version", type=int)
    p.add_argument("--author", default="")
    p.add_argument("--note", default="")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--parent", type=int)
    p.add_argument("--token")
    p.add_argument("--read-only", action="store_true")
    args = p.parse_args(argv)
    s = ScannerService(args.db, args.read_only or os.environ.get("MOTO_READ_ONLY", "0").lower() in {"1", "true", "yes"})
    try:
        if args.command in {"list", "current"}:
            result = s.list()
            result = result["current"] if args.command == "current" else result
        elif args.command in {"validate", "compare"}:
            if not args.file:
                p.error("Informe o arquivo .xlsx")
            f = Path(args.file)
            if f.stat().st_size > s.settings["max_upload_mb"] * 1024 * 1024:
                raise ValueError("Arquivo maior que o limite configurado")
            result = (
                s.validate(f.read_bytes(), f.name)
                if args.command == "validate"
                else s.prepare(f.read_bytes(), f.name, args.author, args.note)
            )
        else:
            if not args.version:
                p.error("Informe --version")
            if args.command == "show":
                result = s.detail(args.version)
            elif args.command == "resume":
                result = s.resume(args.version)
            else:
                result = s.publish(args.version, args.author, args.note, args.confirm, args.parent, args.token)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print("Não foi possível executar: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
