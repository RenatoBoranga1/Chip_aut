"""Operational identity is stricter than aliases/fuzzy and independent of coverage."""

import json
from collections import Counter
from pathlib import Path

from database.repository import encode
from matching.fuzzy_matcher import combined_model, features
from matching.identity import IdentityPolicy
from scanner_base.normalizer import normalize_model, normalize_text, normalize_year

POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "review_queue.json"
SHARED_ACTIONS = {"CONFIRMAR_MATCH", "REJEITAR_CANDIDATO", "NAO_EXISTE_NA_BASE"}
ACTIONS = SHARED_ACTIONS | {"DEIXAR_PENDENTE", "IGNORAR"}


def identity(ad):
    try:
        year = normalize_year(ad.get("year"))
    except ValueError:
        year = None
    return {
        "partner": ad["partner"],
        "manufacturer": normalize_text(ad.get("manufacturer") or ""),
        "model": normalize_model(ad.get("model") or ""),
        "version": normalize_model(ad.get("version") or ""),
        "year": year,
    }


def signature(ad):
    return encode(identity(ad))


def complete_identity(value):
    return bool(value["manufacturer"] and value["model"] and value["year"])


def target_identity(moto):
    return {"manufacturer": normalize_text(moto.manufacturer), "model": normalize_model(moto.model), "year": moto.year}


def memory_scope(action, automatic, policy, target):
    """An ambiguous title cannot identify a trim across different physical ads."""
    if action == "NAO_EXISTE_NA_BASE":
        return "identity"
    if action not in {"CONFIRMAR_MATCH", "REJEITAR_CANDIDATO"} or automatic["match_type"] == "AMBIGUOUS":
        return "advertisement"
    query = automatic["query"]
    engine = IdentityPolicy(policy["matching_rules"].get("identity_policy", {}))
    brand = policy["manufacturer_aliases"].get(
        normalize_text(query["manufacturer"]), normalize_text(query["manufacturer"])
    )
    source, _ = engine.model(brand, combined_model(query["model"], query["version"]))
    destination, _ = engine.model(brand, target.model)
    return (
        "identity"
        if Counter(features(source, brand).tokens) == Counter(features(destination, brand).tokens)
        else "advertisement"
    )


def load_policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def needs_attention(result, policy):
    return (
        result["requires_review"]
        or result["scanner_status"] in policy["attention_statuses"]
        or result["match_type"] in policy["high_match_types"]
    )


def priority(result, state, policy):
    if state in {"resolved", "reused", "ignored", "deferred"}:
        return "low"
    if (
        result["match_type"] in policy["high_match_types"]
        or result["scanner_status"] in policy["high_scanner_statuses"]
    ):
        return "high"
    return "medium"
