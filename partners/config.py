"""Validated partner settings, independent of transport and persistence."""

import json
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

DEFAULT_PARTNER = "wr_motos"
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "partners.json"


def validate_key(key):
    if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key):
        raise ValueError("Chave de parceiro inválida")
    return key


@dataclass(frozen=True)
class PartnerLimits:
    timeout_seconds: float = 30
    retries: int = 2
    delay_seconds: float = 2
    concurrency: int = 1
    max_pages: int = 100

    def __post_init__(self):
        for name, low, high, integer in (
            ("timeout_seconds", 1, 300, False),
            ("retries", 0, 5, True),
            ("delay_seconds", 2, 300, False),
            ("concurrency", 1, 8, True),
            ("max_pages", 1, 1000, True),
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int if integer else (int, float))
                or not low <= value <= high
            ):
                raise ValueError(f"Limite inválido: {name}")

    def apply(self, config):
        return replace(
            config,
            max_retries=self.retries,
            delay_seconds=self.delay_seconds,
            request_timeout_seconds=self.timeout_seconds,
            max_pages=self.max_pages,
        )


@dataclass(frozen=True)
class PartnerSettings:
    partner_key: str
    display_name: str
    collector: str
    enabled: bool = True
    limits: PartnerLimits = field(default_factory=PartnerLimits)
    image_hosts: tuple[str, ...] = ()

    def __post_init__(self):
        validate_key(self.partner_key)
        validate_key(self.collector)
        if (
            not isinstance(self.enabled, bool)
            or not isinstance(self.display_name, str)
            or not self.display_name.strip()
        ):
            raise ValueError("Nome ou habilitação do parceiro inválidos")
        if not isinstance(self.limits, PartnerLimits):
            raise ValueError("Limites do parceiro inválidos")
        for host in self.image_hosts:
            if not isinstance(host, str) or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", host):
                raise ValueError("Origem de imagem inválida")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Configuração duplicada: {key}")
        result[key] = value
    return result


def load_settings(path=None):
    path = Path(path or os.environ.get("MOTO_PARTNERS_CONFIG", DEFAULT_CONFIG))
    raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if set(raw) != {"partners"} or not isinstance(raw["partners"], dict):
        raise ValueError("Configuração de parceiros inválida")
    result = []
    for key, values in raw["partners"].items():
        values = dict(values)
        values["limits"] = PartnerLimits(**values.get("limits", {}))
        values["image_hosts"] = tuple(values.get("image_hosts", []))
        result.append(PartnerSettings(partner_key=key, **values))
    return result
