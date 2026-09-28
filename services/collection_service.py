import logging

from database.partner_repository import PartnerRepository
from database.repository import encode

LOGGER = logging.getLogger(__name__)


def fetch_collection(name, collector):
    from datetime import datetime, timezone

    from partners.models import CollectionResult

    try:
        result = collector.collect() if hasattr(collector, "collect") else collector.collect_motorcycles()
        validate_collection(name, result)
        return result
    except Exception as exc:
        LOGGER.exception("collector_failed partner=%s", name)
        return CollectionResult(
            name, datetime.now(timezone.utc).isoformat(), errors=[{"code": type(exc).__name__, "detail": str(exc)}]
        )


def _collect_partners(collectors, database):
    """Each partner commits independently; one failure does not stop the others."""
    results = []
    for name, collector in collectors.items():
        LOGGER.info(encode({"event": "collection_started", "partner": name}))
        result = fetch_collection(name, collector)
        with PartnerRepository(database) as repo:
            collection_id = repo.save_collection(result)
        LOGGER.info(
            encode(
                {
                    "event": "collection_finished",
                    "partner": name,
                    "collection_id": collection_id,
                    "complete": result.complete,
                    "cached": result.cached,
                    "ads": len(result.advertisements),
                    "errors": len(result.errors),
                }
            )
        )
        results.append((collection_id, result))
    return results


def collect_partners(collectors, database):
    from services.pipeline_lock import ExecutionLock

    results = []
    for name, collector in collectors.items():
        with ExecutionLock(database, partner=name):
            results.extend(_collect_partners({name: collector}, database))
    return results


def validate_collection(name, result):
    from partners.config import validate_key

    validate_key(name)
    if result.partner != name or any(ad.partner != name or not ad.external_id for ad in result.advertisements):
        raise ValueError("Origem ou identidade inválida no resultado da coleta")
    ids = [ad.external_id for ad in result.advertisements]
    if len(ids) != len(set(ids)):
        raise ValueError("IDs duplicados na coleta do parceiro")
