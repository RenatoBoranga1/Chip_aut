from dataclasses import dataclass, field


@dataclass
class PartnerMotorcycle:
    partner: str
    external_id: str
    manufacturer: str | None
    model: str | None
    version: str | None
    year: int | None
    raw_name: str
    source_url: str
    collected_at: str
    raw_text: str
    normalized_key: str | None
    parse_warnings: list[str] = field(default_factory=list)


@dataclass
class CatalogPage:
    scope: str
    number: int
    url: str
    html: str
    collected_at: str


@dataclass
class CollectionResult:
    partner: str
    collected_at: str
    advertisements: list[PartnerMotorcycle] = field(default_factory=list)
    complete: bool = False
    cached: bool = False
    method: str = "Playwright + HTML XHR público + BeautifulSoup"
    duration_seconds: float = 0.0
    pages: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
