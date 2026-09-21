from abc import ABC, abstractmethod

from partners.models import CollectionResult


class PartnerCollector(ABC):
    @abstractmethod
    def collect_motorcycles(self) -> CollectionResult:
        """Return observations and completeness; failures never imply an empty stock."""
