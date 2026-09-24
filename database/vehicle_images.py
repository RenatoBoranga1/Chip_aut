"""Latest visual observation + image changes; no operational writes."""

from dataclasses import asdict

from matching.review_policy import signature
from partners.images import IMAGE_FIELDS


def save_vehicle_images(connection, result):
    if result.cached:
        return
    for ad in result.advertisements:
        identity = signature(asdict(ad))
        previous = connection.execute(
            "SELECT identity_signature,primary_image_url,image_source,image_last_seen_at,observed_at "
            "FROM partner_vehicle_images WHERE partner=? AND external_id=?",
            (ad.partner, ad.external_id),
        ).fetchone()
        if previous and previous[4] > ad.collected_at:
            continue
        photo = (ad.primary_image_url, ad.image_source, ad.image_last_seen_at)
        if not photo[0] and previous and previous[0] == identity:
            photo = previous[1:4]  # Keep last useful image, with its actual last-seen time.
        if not previous or (identity, photo[0]) != previous[:2]:
            connection.execute(
                "INSERT INTO partner_vehicle_image_history(partner,external_id,identity_signature,primary_image_url,image_source,observed_at) VALUES (?,?,?,?,?,?)",
                (ad.partner, ad.external_id, identity, photo[0], photo[1], ad.collected_at),
            )
        connection.execute(
            "INSERT INTO partner_vehicle_images VALUES (?,?,?,?,?,?,?) ON CONFLICT(partner,external_id) DO UPDATE SET "
            "identity_signature=excluded.identity_signature,primary_image_url=excluded.primary_image_url,"
            "image_source=excluded.image_source,image_last_seen_at=excluded.image_last_seen_at,observed_at=excluded.observed_at",
            (ad.partner, ad.external_id, identity, *photo, ad.collected_at),
        )


def latest_vehicle_image(connection, ad):
    defaults = {k: ad.get(k) for k in IMAGE_FIELDS}
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='partner_vehicle_images'").fetchone():
        return defaults
    row = connection.execute(
        "SELECT primary_image_url,image_source,image_last_seen_at FROM partner_vehicle_images "
        "WHERE partner=? AND external_id=? AND identity_signature=?",
        (ad["partner"], ad["external_id"], signature(ad)),
    ).fetchone()
    result = dict(zip(IMAGE_FIELDS, row)) if row else defaults
    previous = connection.execute(
        "SELECT primary_image_url,image_source FROM partner_vehicle_image_history WHERE partner=? AND external_id=? AND identity_signature=? AND primary_image_url IS NOT NULL ORDER BY id DESC LIMIT 4",
        (ad["partner"], ad["external_id"], signature(ad)),
    ).fetchall()
    result["cached_image_urls"] = list(dict.fromkeys(url for url, _ in previous))[:3]
    result["detail_image_url"] = next((url for url, source in previous if source == "detail"), None)
    return result
