import logging

from database.partner_repository import PartnerRepository
from database.repository import encode

LOGGER = logging.getLogger(__name__)


def collect_partners(collectors, database):
    """Each partner commits independently; one failure does not stop the others."""
    from datetime import datetime, timezone

    from partners.models import CollectionResult

    results = []
    for name, collector in collectors.items():
        LOGGER.info(encode({"event": "collection_started", "partner": name}))
        try:
            result = collector.collect_motorcycles()
        except Exception as exc:
            LOGGER.exception("collector_failed partner=%s", name)
            result = CollectionResult(
                name, datetime.now(timezone.utc).isoformat(), errors=[{"code": type(exc).__name__, "detail": str(exc)}]
            )
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
