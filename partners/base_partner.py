from abc import ABC, abstractmethod

from partners.models import CollectionResult


class PartnerCollector(ABC):
    @abstractmethod
    def collect_motorcycles(self) -> CollectionResult:
        """Return observations and completeness; failures never imply an empty stock."""


class PartnerAdapter(PartnerCollector):
    """Canonical adapter; optional capabilities never imply mandatory ad fields."""

    partner_key = ""
    display_name = ""
    enabled = True
    supports_detail_lookup = False
    supports_images = False
    supports_price = False
    supports_mileage = False
    supports_zero_km = False
    max_concurrency = 1

    def collect(self) -> CollectionResult:
        return self.collect_motorcycles()

    def normalize_ad(self, ad):
        from partners.normalization import normalize_advertisement

        return normalize_advertisement(ad, getattr(self, "aliases", {}))

    @classmethod
    def for_pipeline(cls, settings, config, folder):
        adapter = cls()
        adapter.display_name, adapter.enabled = settings.display_name, settings.enabled
        adapter.detail_lookup, adapter.image_fetch = settings.detail_lookup, settings.image_fetch
        return adapter
