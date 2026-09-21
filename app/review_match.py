import argparse
import json
import logging
from pathlib import Path

from database.matching_repository import MatchingRepository


def main():
    parser = argparse.ArgumentParser(description="Fila e decisões auditáveis de revisão do matching")
    parser.add_argument("--db", type=Path, default=Path("data/coverage.sqlite3"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Listar pendências")
    show = sub.add_parser("show", help="Ver resultado e histórico de decisões")
    show.add_argument("run_id", type=int)
    decide = sub.add_parser("decide", help="Registrar decisão sem apagar o resultado automático")
    decide.add_argument("run_id", type=int)
    choice = decide.add_mutually_exclusive_group(required=True)
    choice.add_argument("--candidate", help="Chave de um candidato exibido")
    choice.add_argument("--no-match", action="store_true")
    decide.add_argument("--reviewer", required=True)
    decide.add_argument("--note", required=True)
    memory = sub.add_parser(
        "remember", help="Persistir confirmação, rejeição de par ou revogação para futuras consultas"
    )
    memory.add_argument("run_id", type=int)
    memory.add_argument("--candidate", required=True)
    memory.add_argument("--decision", choices=["CONFIRMAR", "REJEITAR", "REVOGAR"], required=True)
    memory.add_argument("--reviewer", required=True)
    memory.add_argument("--note", required=True)
    args = parser.parse_args()
    try:
        if not args.db.is_file():
            raise ValueError("Banco não encontrado")
        with MatchingRepository(args.db) as repository:
            if args.command == "list":
                result = repository.pending_matches()
            elif args.command == "show":
                result = repository.get_match(args.run_id)
            elif args.command == "remember":
                result = repository.remember_match(args.run_id, args.candidate, args.decision, args.reviewer, args.note)
            else:
                result = repository.review_match(args.run_id, args.candidate, args.reviewer, args.note)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception:
        logging.getLogger(__name__).exception("review_failed")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
