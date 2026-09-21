from dataclasses import dataclass, field


@dataclass(frozen=True)
class MotorcycleQuery:
    manufacturer: str
    model: str
    year: int | str | None
    version: str = ""


@dataclass(frozen=True)
class Candidate:
    scanner_key: str
    manufacturer: str
    model: str
    year: int
    scanner_status: str
    confidence: float | None
    reasons: list[str]
    blockers: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MatchResult:
    query: MotorcycleQuery
    normalized_key: str | None
    match_type: str
    confidence: float | None
    scanner_key: str | None
    scanner_status: str | None
    requires_review: bool
    reasons: list[str]
    candidates: list[Candidate]
    candidates_total: int = 0
    identity_evidence: dict = field(default_factory=dict)
