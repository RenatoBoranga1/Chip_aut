"""No collection/network: regenerate coverage from current saved advertisements."""

from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from database.repository import SQLiteRepository
from database.review_repository import ReviewRepository
from services.coverage_service import build_coverage


def refresh_operational(database):
    with SQLiteRepository(database) as repo:
        groups = defaultdict(set)
        for cid, external_id in repo.connection.execute(
            "SELECT latest_collection_id,external_id FROM partner_advertisements WHERE not_seen_in_latest_collection=0"
        ):
            groups[cid].add(external_id)
    with TemporaryDirectory(prefix="scanner-derived-") as folder:
        for cid, identifiers in groups.items():
            build_coverage(cid, database, Path(folder) / str(cid), external_ids=identifiers)
    with ReviewRepository(database) as repo:
        base_id, _, motos = repo.matching_snapshot()
        base = {m.key: m for m in motos}
        for (item_id,) in repo.connection.execute("SELECT id FROM review_items WHERE active=1").fetchall():
            repo._refresh(item_id, base_id, base)


def safe_resume(database):
    from database.development_repository import read_connection
    from database.scanner_repository import installed
    from services.scanner_service import ScannerService

    try:
        with read_connection(database) as db:
            ids = (
                [r[0] for r in db.execute("SELECT version_id FROM scanner_jobs WHERE status='PENDING'")]
                if installed(db)
                else []
            )
        for identifier in ids:
            ScannerService(database).resume(identifier)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("scanner_job_retry_failed")
