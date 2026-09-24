import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from partners.base_partner import PartnerCollector
from partners.models import CollectionResult, PartnerMotorcycle
from partners.normalization import normalize_advertisement
from partners.wr_http import WRHTTPSource
from partners.wr_parser import parse_catalog_page
from services.import_service import load_rules
from services.vehicle_image_config import load_image_config

LOGGER = logging.getLogger(__name__)


class WRMotosCollector(PartnerCollector):
    def __init__(self, source=None, cache_file=None, cache_ttl=300, aliases=None):
        self.source = source or WRHTTPSource()
        self.cache_file = Path(cache_file) if cache_file else None
        self.cache_ttl = cache_ttl
        self.aliases = aliases if aliases is not None else load_rules()["manufacturer_aliases"]

    def collect_motorcycles(self):
        start = time.perf_counter()
        if self.cache_file and self.cache_file.exists() and self.cache_ttl > 0:
            try:
                saved = json.loads(self.cache_file.read_text(encoding="utf-8"))
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(saved["collected_at"])).total_seconds()
                if (
                    saved.get("metadata", {}).get("cache_schema") == 3
                    and saved["complete"]
                    and 0 <= age < self.cache_ttl
                ):
                    saved["advertisements"] = [PartnerMotorcycle(**item) for item in saved["advertisements"]]
                    saved["cached"] = True
                    saved["duration_seconds"] = round(time.perf_counter() - start, 3)
                    LOGGER.info("collection_cache_hit")
                    return CollectionResult(**saved)
            except (ValueError, KeyError, TypeError):
                LOGGER.exception("invalid_collection_cache")
        result = CollectionResult("wr_motos", datetime.now(timezone.utc).isoformat())
        result.method = getattr(self.source, "method", result.method)
        by_id = {}
        scope_ids = defaultdict(set)
        scope_cards = defaultdict(int)
        signatures = defaultdict(set)
        last_page = defaultdict(int)
        observations = 0
        duplicates = 0
        try:
            for page in self.source.pages():
                if len(result.pages) >= getattr(self.source, "max_pages", 100):
                    raise RuntimeError("Limite de páginas excedido")
                if page.scope not in {"0", "1"} or page.number != last_page[page.scope] + 1:
                    raise RuntimeError("Paginação não avança sequencialmente no filtro")
                ads, errors, count = parse_catalog_page(page.html, self.source.brands, page.collected_at)
                ids = {a.external_id for a in ads}
                signature = hashlib.sha256(page.html.encode()).hexdigest()
                repeated = signature in signatures[page.scope] or (ids and ids <= scope_ids[page.scope])
                signatures[page.scope].add(signature)
                last_page[page.scope] = page.number
                scope_ids[page.scope].update(ids)
                scope_cards[page.scope] += count
                observations += count
                result.errors.extend({**e, "page": page.number, "scope": page.scope} for e in errors)
                result.pages.append({"scope": page.scope, "page": page.number, "url": page.url, "cards": count})
                for ad in ads:
                    normalize_advertisement(ad, self.aliases)
                    ad.zero_km = page.scope == "1"
                    ad.raw_data.update(
                        scope=page.scope, page=page.number, response_url=page.url, response_sha256=signature
                    )
                    if ad.external_id in by_id:
                        duplicates += 1
                        old = by_id[ad.external_id]
                        if not old.primary_image_url and ad.primary_image_url:
                            old.primary_image_url = ad.primary_image_url
                            old.image_source = ad.image_source
                            old.image_last_seen_at = ad.image_last_seen_at
                        if (old.raw_name, old.year, old.price, old.mileage) != (
                            ad.raw_name,
                            ad.year,
                            ad.price,
                            ad.mileage,
                        ):
                            result.errors.append(
                                {
                                    "code": "CONFLICTING_AD",
                                    "external_id": ad.external_id,
                                    "before": old.raw_name,
                                    "after": ad.raw_name,
                                }
                            )
                        if old.zero_km != ad.zero_km:
                            old.zero_km = None
                            old.parse_warnings.append("FILTROS_ZERO_KM_CONFLITANTES")
                        old.raw_data.setdefault("duplicate_observations", []).append(asdict(ad))
                        continue
                    by_id[ad.external_id] = ad
                if repeated:
                    raise RuntimeError("Página/conjunto de external_ids repetido; paginação não avança")
            missing = {"0", "1"} - set(last_page)
            if missing:
                result.errors.append({"code": "MISSING_SCOPE", "scopes": sorted(missing)})
            result.complete = not result.errors and bool(result.pages)
        except Exception as exc:
            LOGGER.exception("partner_collection_failed")
            result.errors.append({"code": type(exc).__name__, "detail": str(exc)})
        result.advertisements = list(by_id.values())
        images = {"detail_attempts": 0, "detail_failures": 0, "detail_skipped": 0, "detail_placeholders_rejected": 0}
        if result.complete and hasattr(self.source, "fill_missing_images"):
            try:
                images.update(self.source.fill_missing_images(result.advertisements, load_image_config()))
            except Exception:
                images["detail_failures"] += 1
                LOGGER.exception("Optional image metadata unavailable")
        images.update(
            with_image=sum(bool(a.primary_image_url) for a in result.advertisements),
            without_image=sum(not a.primary_image_url for a in result.advertisements),
            listing=sum(a.image_source == "listing" for a in result.advertisements),
            detail=sum(a.image_source == "detail" for a in result.advertisements),
            placeholders_rejected=sum(a.raw_data.get("image_placeholders_rejected", 0) for a in result.advertisements)
            + images["detail_placeholders_rejected"],
        )
        result.metadata = {
            **self.source.metadata,
            "cache_schema": 3,
            "images": images,
            "scope_counts": {
                scope: {"cards": scope_cards[scope], "unique_ids": len(scope_ids[scope])} for scope in ("0", "1")
            },
            "observed_cards": observations,
            "duplicate_occurrences": duplicates,
            "version_policy": "Versão não separada pelo site; preservada integralmente em model/raw_name",
        }
        result.duration_seconds = round(time.perf_counter() - start, 3)
        if result.complete and self.cache_file:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(asdict(result), ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.cache_file)
        return result
