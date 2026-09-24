"""Bounded image settings, independent of matching and operational priorities."""

import json
import logging
import os
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "vehicle_images.json"


@dataclass(frozen=True)
class VehicleImageConfig:
    enabled: bool = True
    show_for_not_found: bool = True
    show_for_probable_missing: bool = True
    show_for_confirmed_missing: bool = True
    show_for_high_priority_review: bool = True
    cache_enabled: bool = True
    thumbnail_width: int = 140
    request_timeout_seconds: float = 3
    max_image_bytes: int = 5_000_000
    detail_fallback_limit: int = 8

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(f.default, bool) and type(value) is not bool:
                raise ValueError("Configuração de imagem inválida")
        for name, minimum, maximum in (
            ("thumbnail_width", 100, 160),
            ("request_timeout_seconds", 0.1, 5),
            ("max_image_bytes", 1024, 5_000_000),
            ("detail_fallback_limit", 0, 8),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
                raise ValueError("Limite de imagem inválido")
            if name != "request_timeout_seconds" and not isinstance(value, int):
                raise ValueError("Limite de imagem deve ser inteiro")


def load_image_config(path=None):
    try:
        settings = json.loads(
            Path(path or os.environ.get("MOTO_IMAGES_CONFIG", DEFAULT_CONFIG)).read_text(encoding="utf-8")
        )
        return VehicleImageConfig(**settings)
    except (OSError, ValueError, TypeError):
        logging.getLogger(__name__).exception("Configuração de fotos inválida; fotos desabilitadas")
        return VehicleImageConfig(enabled=False)


def should_show_vehicle_image(row, config=None, *, alert_type=None):
    config = config or load_image_config()
    if not config.enabled:
        return False
    kind = row.get("effective_type") or row.get("matching")
    if kind == "CONFIRMADO_AUSENTE_NA_BASE":
        return config.show_for_confirmed_missing
    if alert_type == "NOVO_ANUNCIO":
        return row.get("coverage") != "SUPORTADO"
    if alert_type == "POSSIVEL_NOVA_MOTO" or row.get("evidence"):
        return config.show_for_probable_missing
    if kind == "NAO_ENCONTRADA_NA_BASE":
        return config.show_for_not_found
    return config.show_for_high_priority_review and (
        alert_type == "REVISAO_ALTA_PRIORIDADE"
        or (row.get("priority") == "high" and row.get("state") in {"pending", "invalidated"})
    )
