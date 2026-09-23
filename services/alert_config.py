"""Central, validated operational alert policy."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config/alerts.json"


@dataclass(frozen=True)
class AlertConfig:
    enabled: bool = True
    failure_high_after: int = 3
    failure_critical_after: int = 5
    new_ad_enabled: bool = True
    probable_missing_enabled: bool = True
    unsupported_enabled: bool = True
    partial_support_enabled: bool = True
    high_priority_review_enabled: bool = True
    stale_decision_enabled: bool = True
    base_version_enabled: bool = True
    failure_enabled: bool = True
    partial_collection_enabled: bool = True

    def __post_init__(self):
        for key, value in vars(self).items():
            if key.endswith("enabled") and type(value) is not bool:
                raise ValueError("Habilitação de alertas deve ser booleana")
        if any(type(v) is not int for v in (self.failure_high_after, self.failure_critical_after)):
            raise ValueError("Limiares de falha devem ser inteiros")
        if not 1 <= self.failure_high_after < self.failure_critical_after:
            raise ValueError("Limiares de falha inválidos")


def load_alert_config(path=None):
    return AlertConfig(
        **json.loads(Path(path or os.environ.get("MOTO_ALERTS_CONFIG", DEFAULT_CONFIG)).read_text(encoding="utf-8"))
    )
