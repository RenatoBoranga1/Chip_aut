import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from scanner_base.normalizer import normalize_text

DEFAULT_MATCHING_RULES = Path(__file__).resolve().parents[1] / "config" / "matching.json"


@dataclass(frozen=True)
class MatchingRules:
    policy_version: str
    candidate_threshold: float
    probable_threshold: float
    ambiguity_margin: float
    max_candidates: int
    weights: dict[str, float]
    version_penalty: float
    protected_tokens: list[str]
    notes: str
    identity_policy: dict = field(default_factory=dict)

    def __post_init__(self):
        from matching.identity import validate_policy

        validate_policy(self.identity_policy)
        numbers = [self.candidate_threshold, self.probable_threshold, self.ambiguity_margin, self.version_penalty]
        if any(type(n) not in (int, float) or not math.isfinite(n) for n in numbers):
            raise ValueError("Limiares precisam ser números finitos")
        if not 0 < self.candidate_threshold <= self.probable_threshold < 100:
            raise ValueError("Exige 0 < candidate_threshold <= probable_threshold < 100")
        if not 0 < self.ambiguity_margin <= 100 or not 0 <= self.version_penalty <= 100:
            raise ValueError("Margem de ambiguidade ou penalidade inválida")
        if type(self.max_candidates) is not int or not 1 <= self.max_candidates <= 100:
            raise ValueError("max_candidates deve ser inteiro de 1 a 100")
        if set(self.weights) != {"token_sort", "token_set", "compact"}:
            raise ValueError("Pesos devem especificar token_sort, token_set e compact")
        if any(type(w) not in (int, float) or not math.isfinite(w) or w < 0 for w in self.weights.values()):
            raise ValueError("Pesos precisam ser números finitos não negativos")
        if not math.isclose(sum(self.weights.values()), 1.0):
            raise ValueError("Pesos devem somar 1")
        if not self.protected_tokens or any(not isinstance(t, str) or not t for t in self.protected_tokens):
            raise ValueError("Tokens de versão protegidos são obrigatórios")

    def to_dict(self):
        return asdict(self)


def load_matching_rules(path: Path = DEFAULT_MATCHING_RULES) -> MatchingRules:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "identity_policy_file" in data:
        data["identity_policy"] = json.loads(
            (Path(path).parent / data.pop("identity_policy_file")).read_text(encoding="utf-8")
        )
    data["protected_tokens"] = [normalize_text(t) for t in data["protected_tokens"]]
    return MatchingRules(**data)
