"""Strict, versioned deterministic policy. Weights are operational hypotheses."""

import hashlib
import json
import math
import os
from copy import deepcopy
from pathlib import Path

from partners.config import unique_object

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config/prioritization.json"
GROUPS = {"base_status", "recurrence", "pending_time", "development", "operational_evidence", "data_quality"}
BASE_FACTORS = {
    "confirmed_absent",
    "unsupported",
    "partial_support",
    "not_found",
    "ambiguous",
    "unknown_support",
    "review",
    "supported",
}
PRIORITIES = {"high": "Alta", "medium": "Média", "low": "Baixa", "unassessed": "Não avaliada"}
CONFIDENCE = {
    "sufficient": "Evidência suficiente",
    "partial": "Evidência parcial",
    "insufficient": "Dados insuficientes",
}


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def validate_policy(raw):
    keys = {
        "version",
        "enabled",
        "score_min",
        "score_max",
        "thresholds",
        "weights",
        "base_factors",
        "pending_full_days",
        "recurrence_full_days",
        "freshness_days",
        "stale_after_hours",
        "reassess_hours",
        "high_pending_days",
        "allow_manual_override",
        "alerts_enabled",
    }
    if not isinstance(raw, dict) or set(raw) != keys:
        raise ValueError("Política incompleta ou com campos desconhecidos")
    if type(raw["version"]) is not int or raw["version"] != 1:
        raise ValueError("Versão da política não suportada")
    if any(type(raw[k]) is not bool for k in ("enabled", "allow_manual_override", "alerts_enabled")):
        raise ValueError("Habilitação da política inválida")
    if (
        type(raw["score_min"]) is not int
        or type(raw["score_max"]) is not int
        or (raw["score_min"], raw["score_max"]) != (0, 100)
    ):
        raise ValueError("A escala deve ser de 0 a 100")
    weights = raw["weights"]
    if (
        not isinstance(weights, dict)
        or set(weights) != GROUPS
        or not all(number(v, 0, 100) for v in weights.values())
        or sum(weights.values()) <= 0
    ):
        raise ValueError("Pesos inválidos")
    factors = raw["base_factors"]
    if (
        not isinstance(factors, dict)
        or set(factors) != BASE_FACTORS
        or not all(number(v, 0, 1) for v in factors.values())
    ):
        raise ValueError("Fatores inválidos")
    thresholds = raw["thresholds"]
    if (
        not isinstance(thresholds, dict)
        or set(thresholds) != {"high", "medium"}
        or not all(number(v, 1, 100) for v in thresholds.values())
        or thresholds["medium"] >= thresholds["high"]
    ):
        raise ValueError("Faixas inválidas")
    for key in (
        "pending_full_days",
        "recurrence_full_days",
        "freshness_days",
        "stale_after_hours",
        "reassess_hours",
        "high_pending_days",
    ):
        if not number(raw[key], 1, 3650):
            raise ValueError("Prazo inválido: " + key)
    if raw["reassess_hours"] > raw["stale_after_hours"]:
        raise ValueError("Reavaliação deve ocorrer antes do prazo de desatualização")
    return deepcopy(raw)


def load_policy(path=None):
    return validate_policy(
        json.loads(
            Path(path or os.environ.get("MOTO_PRIORITIZATION_CONFIG", DEFAULT_CONFIG)).read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
        )
    )


def policy_hash(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
