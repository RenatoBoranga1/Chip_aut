"""Validated external settings and timezone-aware scheduling; no collection logic."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config/scheduler.json"


def utcnow():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SchedulerConfig:
    enabled: bool = True
    timezone: str = "America/Sao_Paulo"
    frequency: str = "daily"
    hour: int = 7
    minute: int = 0
    interval_hours: float = 12
    max_retries: int = 2
    retry_backoff_seconds: float = 30
    heartbeat_seconds: float = 10
    activity_timeout_seconds: float = 90
    delay_seconds: float = 2
    request_timeout_seconds: float = 30
    max_pages: int = 100
    reports: str = "reports/pipeline"
    log_file: str = "logs/pipeline.log"

    def __post_init__(self):
        ZoneInfo(self.timezone)
        if type(self.enabled) is not bool or self.frequency not in {"daily", "interval"}:
            raise ValueError("Habilitação ou frequência inválida")
        for key, low, high in (("hour", 0, 23), ("minute", 0, 59), ("max_retries", 0, 5), ("max_pages", 1, 1000)):
            v = getattr(self, key)
            if type(v) is not int or not low <= v <= high:
                raise ValueError(f"Configuração inválida: {key}")
        for key, low, high in (
            ("interval_hours", 1 / 60, 8760),
            ("retry_backoff_seconds", 0, 300),
            ("heartbeat_seconds", 0.1, 60),
            ("activity_timeout_seconds", 1, 3600),
            ("delay_seconds", 2, 300),
            ("request_timeout_seconds", 1, 300),
        ):
            v = getattr(self, key)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not low <= v <= high:
                raise ValueError(f"Configuração inválida: {key}")
        if self.activity_timeout_seconds < 3 * self.heartbeat_seconds:
            raise ValueError("Prazo do sinal de atividade deve ser pelo menos três intervalos")
        if not all(isinstance(v, str) and v.strip() for v in (self.reports, self.log_file)):
            raise ValueError("Caminhos de relatórios e logs obrigatórios")

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def load_config(path=DEFAULT_CONFIG):
    return SchedulerConfig(**json.loads(Path(path).read_text(encoding="utf-8")))


def next_due(config, after):
    if after.tzinfo is None:
        raise ValueError("Horário deve incluir fuso explícito")
    if config.frequency == "interval":
        return after.astimezone(timezone.utc) + timedelta(hours=config.interval_hours)
    zone = ZoneInfo(config.timezone)
    local = after.astimezone(zone)
    for days in range(3):
        candidate = (local + timedelta(days=days)).replace(
            hour=config.hour, minute=config.minute, second=0, microsecond=0, fold=0
        )
        # A nonexistent wall time moves forward through the gap; ambiguous times run only at fold=0.
        candidate = candidate.astimezone(timezone.utc).astimezone(zone)
        if candidate.astimezone(timezone.utc) > after.astimezone(timezone.utc):
            return candidate.astimezone(timezone.utc)
    raise ValueError("Não foi possível calcular o próximo horário")
