"""CLI for explicit human decisions; no commands manufacture reviewer decisions."""

import argparse
import json
from pathlib import Path

from database.review_repository import ReviewRepository

COMMANDS = {
    "confirm": "CONFIRMAR_MATCH",
    "reject": "REJEITAR_CANDIDATO",
    "no-match": "NAO_EXISTE_NA_BASE",
    "defer": "DEIXAR_PENDENTE",
    "ignore": "IGNORAR",
}


def render(item):
    ad = item["advertisement"]
    auto, effective = item["automatic"], item["effective"]
    lines = [
        f"REVISÃO {item['id']} | {item['state']} | prioridade {item['priority']}",
        f"ANÚNCIO: {ad['partner']} / {ad['external_id']} | {ad['manufacturer']} | {ad['model']} | versão {ad['version'] or '—'} | {ad['year']}",
        f"URL: {ad['source_url']}",
        f"Original: {ad['raw_name']}",
        f"Coleta {item['collection_id']} / matching {item['run_id']} / base atual {item['evaluated_import_id']}",
        f"AUTOMÁTICO: {auto['match_type']} | score {auto['confidence']} | {'; '.join(auto['reasons'])}",
        "CANDIDATOS AUTOMÁTICOS (não confirmam suporte):",
    ]
    lines.extend(
        f"  {c['scanner_key']} | {c['model']} | {c['year']} | score {c['confidence']} | {c['scanner_status']}"
        for c in auto["candidates"]
    )
    lines += [
        f"EFETIVO: {effective['match_type']} | identidade {effective['scanner_key']} | cobertura {effective['scanner_status']}",
        "MEMÓRIA: " + json.dumps(item["memory"], ensure_ascii=False),
        "HISTÓRICO (inclui decisões compartilhadas):",
    ]
    lines.extend(
        f"  #{d['id']} item {d['review_item_id']} | {d['action']} | {d['reviewer']} | {d['created_at']} | base {d['import_id']} | {d['candidate_key']} | {d['note']}"
        for d in item.get("history", [])
    )
    lines.extend(f"  Evento: {e['reason']} | {e['created_at']}" for e in item.get("events", []))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Fila operacional auditável; identidade não altera suporte")
    parser.add_argument("--db", type=Path, default=Path("data/coverage.sqlite3"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--status", choices=["pending", "resolved", "ignored", "deferred", "invalidated", "reused"])
    listing.add_argument("--priority", choices=["high", "medium", "low"])
    listing.add_argument("--include-inactive", action="store_true")
    for name in ("show", "history", *COMMANDS):
        command = commands.add_parser(name)
        command.add_argument("item_id", type=int)
        if name in COMMANDS:
            command.add_argument("--reviewer", required=True)
            command.add_argument("--note", required=True)
            if name in {"confirm", "reject"}:
                command.add_argument("--candidate", required=True)
    args = parser.parse_args()
    try:
        if not args.db.is_file():
            raise ValueError("Banco não encontrado; importe a base e gere cobertura primeiro")
        with ReviewRepository(args.db) as repo:
            if args.command == "list":
                result = repo.list_items(args.status, args.priority, args.include_inactive)
                output = (
                    "\n".join(
                        f"{i['id']} | {i['state']} | {i['priority']} | {i['partner']}/{i['external_id']} | {i['advertisement']['raw_name']} | {i['advertisement']['year']}"
                        for i in result
                    )
                    or "Fila vazia para estes filtros."
                )
            elif args.command in COMMANDS:
                result = repo.decide(
                    args.item_id, COMMANDS[args.command], args.reviewer, args.note, getattr(args, "candidate", None)
                )
                output = render(result)
            else:
                result = repo.show(args.item_id)
                output = render(result)
        # ASCII JSON remains valid UTF-8 under Windows pipe codepages as well.
        print(json.dumps(result, ensure_ascii=True, indent=2) if args.as_json else output)
    except ValueError as exc:
        parser.exit(2, f"Erro: {exc}\n")


if __name__ == "__main__":
    main()
