"""Read-only labels derived from the existing, revalidated human decisions."""

from urllib.parse import urlencode


def decision_state(review, effective):
    if review and (review.get("stale_reason") or review.get("state") == "invalidated"):
        return "Pendente"
    decision = (review or {}).get("human_decision")
    if decision:
        return {
            "CONFIRMAR_MATCH": "Existe na base",
            "NAO_EXISTE_NA_BASE": "Não existe na base",
            "DEIXAR_PENDENTE": "Em dúvida",
        }.get(decision["action"], "Pendente")
    # This result is produced only by the pre-existing, audited manual memory.
    if effective["match_type"] == "CONFIRMADO_MANUALMENTE" and effective.get("scanner_key"):
        return "Existe na base"
    return "Pendente"


def presentation(automatic, effective, review=None, partner_state=None):
    human = decision_state(review, effective)
    base = {
        "Existe na base": "Existe na base — confirmado",
        "Não existe na base": "Ausência confirmada",
        "Em dúvida": "Em dúvida",
    }.get(human)
    if base is None:
        base = (
            "Correspondência automática encontrada"
            if effective["match_type"] == "EXATO_NORMALIZADO"
            else "Correspondência ambígua"
            if effective["match_type"] == "AMBIGUOUS"
            else "Pendente de confirmação"
        )
    reasons = []
    if partner_state == "Novo anúncio":
        reasons.append("Novo anúncio do parceiro")
    reason = {
        "NAO_ENCONTRADA_NA_BASE": "Não encontrado automaticamente na base",
        "AMBIGUOUS": "Correspondência ambígua",
        "CORRESPONDENCIA_PROVAVEL": "Correspondência aproximada",
        "REVISAR": "Identidade exige revisão",
        "AGUARDANDO_MATCHING": "Aguardando comparação com a base",
    }.get(automatic["match_type"])
    if reason:
        reasons.append(reason)
    if effective.get("scanner_status") in {"SEM_SUPORTE", "SUPORTE_PARCIAL"} and not effective.get(
        "requires_review", True
    ):
        reasons.append(
            {"SEM_SUPORTE": "Sem suporte", "SUPORTE_PARCIAL": "Suporte parcial"}[effective["scanner_status"]]
        )
    return {
        "human_status": human,
        "base_status": base,
        "partner_status": partner_state or "Situação não disponível",
        "pending_origin": " · ".join(reasons)
        or (
            "Situação de suporte não definida"
            if effective.get("scanner_status") == "SEM_STATUS"
            else "Sem pendência de identidade identificada"
        ),
        "decision_action": "Ver / alterar decisão"
        if (review or {}).get("human_decision") or human != "Pendente"
        else "Registrar decisão",
    }


def decision_link(row):
    if not row.get("id"):
        return "Revisão ainda não disponível"
    query = urlencode({"review": row["id"], "partner": row["partner"]})
    return f"[{row['decision_action']}](?{query})"
