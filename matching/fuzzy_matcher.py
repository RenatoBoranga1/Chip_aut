"""Explainable similarities. Version evidence is retained, never an alias."""

import re
from collections import Counter
from dataclasses import dataclass

from rapidfuzz import fuzz

from matching.models import Candidate
from matching.rules import MatchingRules
from scanner_base.models import Motorcycle
from scanner_base.normalizer import normalize_model, normalize_text


@dataclass(frozen=True)
class ModelFeatures:
    compact: str
    tokens: tuple[str, ...]
    numbers: tuple[str, ...]
    displacement: str | None


def features(model: str, manufacturer: str = "") -> ModelFeatures:
    text = normalize_text(model)
    # A repeated manufacturer at the start is descriptive, not a trim.
    if manufacturer and text.startswith(normalize_text(manufacturer) + " "):
        text = text[len(normalize_text(manufacturer)) :].strip()
    # Preserve unknown punctuation rather than silently deleting potential versions.
    tokens = tuple(re.findall(r"[A-Z]+|\d+(?:[.,]\d+)?|[^\w\s\-‐‑‒–—]", text))
    numbers = tuple(t.replace(",", ".") for t in tokens if t[0].isdigit())
    # Conservative numeric model signature, not a claim about actual engine cc.
    primary = next((n for n in numbers if float(n) >= 50), numbers[0] if numbers else None)
    return ModelFeatures(normalize_model(text), tokens, numbers, primary)


def combined_model(model: str, version: str) -> str:
    if not version.strip():
        return model.strip()
    # Avoid duplicating a separate version only when it is a complete token suffix.
    model_tokens, version_tokens = features(model).tokens, features(version).tokens
    if version_tokens and model_tokens[-len(version_tokens) :] == version_tokens:
        return model.strip()
    return f"{model.strip()} {version.strip()}"


def compare_features(
    query: ModelFeatures,
    motorcycle: Motorcycle,
    target: ModelFeatures,
    rules: MatchingRules,
    include_below_threshold: bool = False,
) -> Candidate | None:
    if query.displacement and target.displacement and query.displacement != target.displacement:
        return None
    components = {
        "token_sort": fuzz.token_sort_ratio(" ".join(query.tokens), " ".join(target.tokens)),
        "token_set": fuzz.token_set_ratio(" ".join(query.tokens), " ".join(target.tokens)),
        "compact": fuzz.ratio(query.compact, target.compact),
    }
    score = sum(components[key] * weight for key, weight in rules.weights.items())
    blockers = []
    reasons = ["Mesma montadora", "Mesmo ano"]
    common = Counter(query.tokens) & Counter(target.tokens)
    if common:
        reasons.append("Tokens comuns: " + " ".join(sorted(common.elements())))
    if query.tokens != target.tokens:
        reasons.append("Sequência de tokens diferente; token_sort reduz o efeito da ordem")
    if query.displacement and target.displacement:
        reasons.append(f"Assinatura numérica principal preservada: {query.displacement}")
    elif query.displacement != target.displacement:
        blockers.append("INFORMACAO_NUMERICA_AUSENTE")
    if Counter(query.numbers) != Counter(target.numbers):
        blockers.append("NUMEROS_DE_MODELO_OU_VERSAO_DIFERENTES")
    protected = set(rules.protected_tokens)
    if (set(query.tokens) & protected) != (set(target.tokens) & protected):
        blockers.append("VERSAO_DIFERENTE_OU_INCOMPLETA")
        score -= rules.version_penalty
    differences = (Counter(query.tokens) - Counter(target.tokens), Counter(target.tokens) - Counter(query.tokens))
    for label, difference in zip(("Só na consulta", "Só na base"), differences):
        if difference:
            reasons.append(f"{label}: {' '.join(sorted(difference.elements()))}")
    if blockers:
        score = min(score, rules.probable_threshold - 0.01)
    score = round(max(0, min(score, 99.0)), 2)
    reasons.append(f"Soma ponderada: {sum(components[k] * w for k, w in rules.weights.items()):.4f}")
    if "VERSAO_DIFERENTE_OU_INCOMPLETA" in blockers:
        reasons.append(f"Penalidade de versão: -{rules.version_penalty:.2f}")
    reasons.append(f"Score final após limites e arredondamento: {score:.2f}")
    if score < rules.candidate_threshold and not include_below_threshold:
        return None
    return Candidate(
        motorcycle.key,
        motorcycle.manufacturer,
        motorcycle.model,
        motorcycle.year,
        motorcycle.status,
        score,
        reasons,
        blockers,
        {k: round(v, 2) for k, v in components.items()},
    )
