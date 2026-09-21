"""Evidence-backed, scoped equivalences. No fuzzy or scanner status here."""

import re

from scanner_base.normalizer import normalize_model, normalize_text

CATEGORIES = ("manufacturer_aliases", "model_aliases", "token_aliases", "known_equivalences", "noise_rules")


def validate_policy(policy):
    if not policy:
        return
    if not isinstance(policy, dict) or not isinstance(policy.get("version"), str):
        raise ValueError("Política de identidade inválida")
    ids = set()
    for category in CATEGORIES:
        if not isinstance(policy.get(category), list):
            raise ValueError(f"Lista obrigatória: {category}")
        for rule in policy[category]:
            if not isinstance(rule, dict) or not rule.get("id") or not rule.get("evidence"):
                raise ValueError("Regra exige id e evidência")
            if rule["id"] in ids:
                raise ValueError("ID de regra duplicado")
            ids.add(rule["id"])
            if category != "noise_rules":
                if any(not isinstance(rule.get(k), str) or not rule[k].strip() for k in ("from", "to")):
                    raise ValueError("Alias exige origem e destino")
                if category != "manufacturer_aliases" and not rule.get("manufacturer"):
                    raise ValueError("Alias de modelo/token exige montadora")
            elif rule.get("kind") == "suffix":
                pattern = rule.get("pattern", "")
                if not pattern.endswith("$") or re.compile(pattern).search(""):
                    raise ValueError("Ruído deve ser sufixo não vazio e ancorado")
            elif rule.get("kind") != "manufacturer_prefix":
                raise ValueError("Tipo de ruído desconhecido")
    if not isinstance(policy.get("protected_tokens", []), list):
        raise ValueError("Tokens protegidos inválidos")
    if policy.get("protected_tokens") and not policy.get("protected_tokens_evidence"):
        raise ValueError("Proteção adicional exige evidência")
    if any(not isinstance(t, str) or not t.strip() for t in policy.get("protected_tokens", [])):
        raise ValueError("Token protegido inválido")
    diagnostic = policy.get("diagnostics", {})
    if diagnostic and (
        not diagnostic.get("evidence")
        or type(diagnostic.get("near_similarity")) not in (int, float)
        or not 0 < diagnostic["near_similarity"] <= 100
        or type(diagnostic.get("max_candidates")) is not int
        or not 1 <= diagnostic["max_candidates"] <= 100
    ):
        raise ValueError("Diagnóstico exige limiar, limite e evidência válidos")


class IdentityPolicy:
    def __init__(self, policy):
        validate_policy(policy)
        self.policy = policy

    def manufacturer(self, value):
        name, steps = normalize_text(value), []
        for rule in self.policy.get("manufacturer_aliases", []):
            if name == normalize_text(rule["from"]):
                steps.append(
                    {
                        "rule_id": rule["id"],
                        "before": name,
                        "after": normalize_text(rule["to"]),
                        "evidence": rule["evidence"],
                    }
                )
                name = normalize_text(rule["to"])
        return name, steps

    def model(self, manufacturer, model):
        value, steps = normalize_text(model), []
        for category in ("noise_rules", "model_aliases", "token_aliases", "known_equivalences"):
            for rule in self.policy.get(category, []):
                if rule.get("manufacturer") and normalize_text(rule["manufacturer"]) != manufacturer:
                    continue
                before = value
                if category == "noise_rules":
                    if rule["kind"] == "manufacturer_prefix":
                        if value.startswith(manufacturer + " "):
                            value = value[len(manufacturer) :].strip()
                    else:
                        value = re.sub(rule["pattern"], "", value).strip()
                        if rule.get("requires_suffix") and not value.endswith(" " + rule["requires_suffix"]):
                            value = before
                elif category == "token_aliases":
                    if rule.get("model_prefix") and not normalize_model(value).startswith(
                        normalize_model(rule["model_prefix"])
                    ):
                        continue
                    value = re.sub(
                        r"(?<![A-Z])" + re.escape(normalize_text(rule["from"])) + r"(?![A-Z])",
                        normalize_text(rule["to"]),
                        value,
                    )
                elif normalize_model(value) == normalize_model(rule["from"]):
                    value = normalize_text(rule["to"])
                if value != before:
                    steps.append(
                        {"rule_id": rule["id"], "before": before, "after": value, "evidence": rule["evidence"]}
                    )
        return value, steps
