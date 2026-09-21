from dataclasses import dataclass, field


@dataclass
class SystemRecord:
    sheet: str
    row: int
    raw: dict[str, str]
    raw_fields: dict[str, str]
    manufacturer: str
    model: str
    year: int
    key: str
    system: str
    system_key: str
    status: str
    status_reason: str
    release: str
    date: str | None
    cable: str
    cable_location: str
    duplicate_of: int | None = None


@dataclass
class Motorcycle:
    key: str
    manufacturer: str
    model: str
    year: int
    normalized_model: str
    status: str
    system_count: int
    record_count: int
    supported_systems: list[str]
    unsupported_systems: list[str]
    analysis_systems: list[str]
    unknown_systems: list[str]
    latest_date: str | None
    releases: list[str]


@dataclass
class ParsedBase:
    records: list[SystemRecord] = field(default_factory=list)
    motorcycles: list[Motorcycle] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    sheets: list[dict] = field(default_factory=list)
    rejected_rows: int = 0
