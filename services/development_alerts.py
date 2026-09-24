"""Development notifications in the existing alert center, without fake pipeline runs."""

import logging
from datetime import datetime

from database.development_repository import DevelopmentRepository
from database.transaction import atomic_database
from services.development_policy import load_development_config
from services.scheduler_config import utcnow


def scan_stale(database, policy=None, clock=utcnow, force=False):
    policy = policy if policy is not None else load_development_config()
    if not policy["enabled"] or not policy["alerts_enabled"]:
        return 0
    # Browsing never calls this. Scheduler/CLI opt into the write operation.
    with atomic_database(database), DevelopmentRepository(database) as repo:
        now = clock()
        last = repo.last_scan()
        if last and not force and (now - datetime.fromisoformat(last)).total_seconds() < 3600:
            return 0
        count = 0
        for status, days in policy["stale_days"].items():
            for row in repo.status_dates(status):
                if (now - datetime.fromisoformat(row[1])).days <= days:
                    continue
                key = f"stale:{row[0]}:{row[1]}"
                count += repo.notify(
                    row[0],
                    "DEV_STALE",
                    key,
                    "ATENCAO",
                    "Item de desenvolvimento aguardando acompanhamento",
                    f"Item permanece nesta situação há mais de {days} dias. Confira o andamento; isto não indica falha.",
                    now.isoformat(),
                )
        repo.save_scan(now.isoformat())
        return count


def safe_scan(database):
    try:
        scan_stale(database)
    except Exception:
        logging.getLogger(__name__).exception(
            "Não foi possível verificar prazos de desenvolvimento; próxima verificação tentará novamente"
        )
