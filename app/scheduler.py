"""Commands for the independent operational scheduler."""

import argparse
import json
import os
from pathlib import Path

from database.pipeline_repository import read_pipeline
from services.pipeline_service import LOGGER, run_pipeline
from services.scheduler_config import DEFAULT_CONFIG, load_config
from services.scheduler_service import scheduler_status, serve
from ui.textos import value


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agendamento e atualização operacional")
    parser.add_argument("command", choices=["start", "run-now", "status", "history", "validate-config"])
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("MOTO_DB", "data/coverage.sqlite3")))
    parser.add_argument(
        "--config", type=Path, default=Path(os.environ.get("MOTO_SCHEDULER_CONFIG", str(DEFAULT_CONFIG)))
    )
    parser.add_argument("--request-key", default=None)
    parser.add_argument("--json", action="store_true", help="Saída técnica para integração")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "validate-config":
            output = {
                "Configuração": "Válida",
                "Fuso horário": config.timezone,
                "Agendamento habilitado": config.enabled,
            }
        elif args.command == "start":
            serve(args.db, args.config)
            output = {"Agendamento": "Encerrado"}
        elif args.command == "run-now":
            output = run_pipeline(args.db, config, request_key=args.request_key)
        elif args.command == "status":
            output = scheduler_status(args.db, config)
        else:
            output = read_pipeline(args.db)
        if args.json or args.command in {"validate-config", "start"}:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        elif args.command == "run-now":
            print(f"Execução {output['id']}: {value(output['status'])}")
            if output.get("error_summary"):
                print("Detalhes da falha disponíveis no histórico e no registro de execução.")
        else:
            if "schedule_status" in output:
                print("Agendamento:", value(output["schedule_status"]))
                print("Próxima atualização prevista:", output["next_local"] or "Sem previsão ativa")
            for run in output["runs"]:
                print(
                    f"Execução {run['id']} · {run['started_at']} · {value(run['trigger_type'])} · {value(run['status'])}"
                )
        if args.command == "run-now" and output["status"] in {"FAILED", "CANCELLED"}:
            return 1
        return 0
    except KeyboardInterrupt:
        print("Agendamento encerrado pelo operador.")
        return 130
    except Exception as exc:
        LOGGER.exception("Falha ao executar comando do agendamento")
        print(f"Não foi possível executar o comando: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
