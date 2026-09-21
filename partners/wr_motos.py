import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from partners.base_partner import PartnerCollector
from partners.models import CollectionResult, PartnerMotorcycle
from partners.wr_browser import WRBrowserSource
from partners.wr_parser import parse_catalog_page
from services.import_service import load_rules

LOGGER = logging.getLogger(__name__)


class WRMotosCollector(PartnerCollector):
    def __init__(self, source=None, cache_file=None, cache_ttl=300, aliases=None):
        self.source = source or WRBrowserSource()
        self.cache_file = Path(cache_file) if cache_file else None
        self.cache_ttl = cache_ttl
        self.aliases = aliases if aliases is not None else load_rules()["manufacturer_aliases"]

    def collect_motorcycles(self):
        start = time.perf_counter()
        if self.cache_file and self.cache_file.exists() and self.cache_ttl > 0:
            try:
                saved = json.loads(self.cache_file.read_text(encoding="utf-8"))
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(saved["collected_at"])).total_seconds()
                if saved["complete"] and 0 <= age < self.cache_ttl:
                    saved["advertisements"] = [PartnerMotorcycle(**item) for item in saved["advertisements"]]
                    saved["cached"] = True
                    saved["duration_seconds"] = round(time.perf_counter() - start, 3)
                    LOGGER.info("collection_cache_hit")
                    return CollectionResult(**saved)
            except (ValueError, KeyError, TypeError):
                LOGGER.exception("invalid_collection_cache")
        result = CollectionResult("wr_motos", datetime.now(timezone.utc).isoformat())
        by_id = {}
        observations = 0
        duplicates = 0
        try:
            for page in self.source.pages():
                ads, errors, count = parse_catalog_page(page.html, self.source.brands, page.collected_at, self.aliases)
                observations += count
                result.errors.extend({**e, "page": page.number, "scope": page.scope} for e in errors)
                result.pages.append({"scope": page.scope, "page": page.number, "url": page.url, "cards": count})
                for ad in ads:
                    if ad.external_id in by_id:
                        duplicates += 1
                        old = by_id[ad.external_id]
                        if (old.raw_name, old.year) != (ad.raw_name, ad.year):
                            result.errors.append(
                                {
                                    "code": "CONFLICTING_AD",
                                    "external_id": ad.external_id,
                                    "before": old.raw_name,
                                    "after": ad.raw_name,
                                }
                            )
                        continue
                    by_id[ad.external_id] = ad
            result.complete = not result.errors and bool(result.pages)
        except Exception as exc:
            LOGGER.exception("partner_collection_failed")
            result.errors.append({"code": type(exc).__name__, "detail": str(exc)})
        result.advertisements = list(by_id.values())
        result.metadata = {
            **self.source.metadata,
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
