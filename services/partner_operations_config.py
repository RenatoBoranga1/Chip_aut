"""Non-secret polling and freshness policy; paths are opt-in environment settings."""

import json
import os
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[1] / "config/partner_operations.json"
INBOX_ENV = {"thomas_motos": "THOMAS_INBOX_PATH", "moto_marques": "MOTO_MARQUES_INBOX_PATH"}


def load_policy():
    data = json.loads(Path(os.environ.get("MOTO_PARTNER_OPERATIONS_CONFIG", DEFAULT)).read_text(encoding="utf-8"))
    for partner in ("thomas_motos", "moto_marques", "motonil"):
        item = data[partner]
        if type(item["stale_after_days"]) is not int or not 1 <= item["stale_after_days"] <= 365:
            raise ValueError("Prazo de desatualização inválido")
        if partner in INBOX_ENV:
            interval = item["scan_interval_minutes"]
            if type(interval) is not int or not 1 <= interval <= 10080:
                raise ValueError("Intervalo da inbox inválido")
    for value in data["anomalies"].values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 1:
            raise ValueError("Limiar de anomalia inválido")
    return data


def inbox_root(partner):
    if partner not in INBOX_ENV:
        raise ValueError("Parceiro sem inbox de arquivos")
    value = os.environ.get(INBOX_ENV[partner])
    return Path(value).expanduser().resolve() if value else None
