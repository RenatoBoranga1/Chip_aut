"""Collection delta uses actual saved observations, not queue size or matching guesses."""

from dataclasses import asdict

from database.partner_repository import PartnerRepository
from matching.review_policy import signature


def collection_changes(collection_id, database):
    with PartnerRepository(database) as repo:
        current = repo.get_collection(collection_id)
        previous = repo.connection.execute(
            "SELECT id FROM partner_collections WHERE partner=? AND id<? AND status='COMPLETE' ORDER BY id DESC LIMIT 1",
            (current.partner, collection_id),
        ).fetchone()
        before = repo.get_collection(previous[0]).advertisements if previous else []
    old = {ad.external_id: asdict(ad) for ad in before}
    new = {ad.external_id: asdict(ad) for ad in current.advertisements}
    common = old.keys() & new.keys()
    fields = (
        "manufacturer",
        "model",
        "version",
        "year",
        "raw_name",
        "raw_text",
        "price",
        "mileage",
        "zero_km",
        "source_url",
    )
    return {
        "previous_collection_id": previous[0] if previous else None,
        "reappeared": len(common),
        "new": len(new.keys() - old.keys()),
        "identity_changed": sum(signature(old[k]) != signature(new[k]) for k in common),
        "data_changed": sum(any(old[k].get(f) != new[k].get(f) for f in fields) for k in common),
        "disappeared": len(old.keys() - new.keys()) if current.complete and not current.cached else None,
        "note": "Disappeared is unknown for partial/cached collections; data_changed ignores collection timestamps and response metadata.",
    }
