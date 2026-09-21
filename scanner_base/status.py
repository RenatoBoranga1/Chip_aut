from scanner_base.normalizer import normalize_text

STATUSES = {"SUPORTADO", "SEM_SUPORTE", "EM_ANALISE", "SEM_STATUS", "SUPORTE_PARCIAL"}


def classify(release: str, situation: str, rules: dict) -> tuple[str, str]:
    release, situation = normalize_text(release), normalize_text(situation)
    a = rules["release_status"].get(release)
    b = rules["situation_status"].get(situation)
    if situation and b is None:
        return "SEM_STATUS", "SIT. sem regra validada"
    if b == "EM_ANALISE" or a == "EM_ANALISE":
        return "EM_ANALISE", "Indicação explícita de análise"
    if a and b and a != b:
        return "SEM_STATUS", "Conflito entre LANC. e SIT."
    if a is None and release:
        return "SEM_STATUS", "LANC. sem regra validada"
    return (b or a or "SEM_STATUS", "Mapeamento explícito" if (a or b) else "Sem indicação")


def aggregate_status(statuses: list[str]) -> str:
    values = set(statuses)
    if {"SUPORTADO", "SEM_SUPORTE"} <= values:
        return "SUPORTE_PARCIAL"
    if "EM_ANALISE" in values:
        return "EM_ANALISE"
    if "SEM_STATUS" in values or not values:
        return "SEM_STATUS"
    if len(values) == 1:
        return next(iter(values))
    return "SUPORTE_PARCIAL"
