"""Pure scoring: no IO, no images, no demand inference and no business writes."""

from datetime import datetime

from services.prioritization_policy import policy_hash, validate_policy


def days_since(value, now):
    try:
        stamp = datetime.fromisoformat(value)
        return max(0, (now - stamp).days) if stamp.tzinfo and stamp <= now else None
    except (TypeError, ValueError):
        return None


def assess(source, policy, now):
    policy = validate_policy(policy)
    evidence = dict(source)
    # Image metadata is presentation only and cannot influence score or confidence.
    effective = source.get("effective_type")
    known = effective not in (None, "AGUARDANDO_MATCHING")
    complete = all(source.get(k) for k in ("manufacturer", "model", "year"))
    unresolved = (
        source.get("human_status") == "Em dúvida"
        or source.get("human_status") == "Pendente"
        and effective
        not in {
            "EXATO_NORMALIZADO",
            "CONFIRMADO_MANUALMENTE",
            "EXATO_CONFIRMADO_HUMANAMENTE",
        }
    )
    if source.get("human_status") == "Em dúvida":
        kind, label = "review", "Usuário manteve dúvida; confirmar identidade"
    elif effective == "CONFIRMADO_AUSENTE_NA_BASE":
        kind, label = "confirmed_absent", "Ausência confirmada na versão vigente da base"
    elif effective in {"EXATO_NORMALIZADO", "CONFIRMADO_MANUALMENTE", "EXATO_CONFIRMADO_HUMANAMENTE"}:
        kind, label = {
            "SEM_SUPORTE": ("unsupported", "Identidade vinculada: suporte ausente declarado na base"),
            "SUPORTE_PARCIAL": ("partial_support", "Identidade vinculada: suporte parcial"),
            "SUPORTADO": ("supported", "Identidade vinculada: suporte declarado"),
        }.get(source.get("coverage"), ("unknown_support", "Identidade vinculada: suporte ainda não definido"))
    else:
        kind, label = {
            "NAO_ENCONTRADA_NA_BASE": ("not_found", "Não encontrada automaticamente; ausência não confirmada"),
            "AMBIGUOUS": ("ambiguous", "Correspondência ambígua exige revisão"),
        }.get(effective, ("review", "Identidade ainda depende de revisão"))
    age = days_since(source.get("first_seen"), now)
    fresh = days_since(source.get("last_seen"), now)
    pending_days = days_since(source.get("pending_since"), now) if known and kind != "supported" else None
    dev = source.get("development")
    active_dev = bool(dev and dev["status"] not in {"COMPLETED", "DISCARDED"})
    dev_days = days_since(dev.get("status_since"), now) if dev else None
    attention = known and kind != "supported"
    signals = []
    denominator = sum(policy["weights"].values())

    def add(group, fraction, reason, observed):
        points = round(100 * policy["weights"][group] * fraction / denominator, 2)
        signals.append({"criterion": group, "points": points, "reason": reason, "evidence": observed})

    if known:
        add(
            "base_status",
            policy["base_factors"][kind],
            label,
            {
                "effective_type": effective,
                "coverage": source.get("coverage"),
                "base_version": source.get("scanner_base_version"),
                "human_status": source.get("human_status"),
            },
        )
    # Repeated executions are not independent demand; only elapsed presence earns a bounded contribution.
    if (
        attention
        and source.get("observations", 0) >= 2
        and age is not None
        and age > 0
        and source.get("distinct_observation_days", 0) >= 2
    ):
        add(
            "recurrence",
            min(age / policy["recurrence_full_days"], 1),
            "Permanência observada em dias distintos; não representa demanda",
            {"observations": source["observations"], "days": age, "distinct_days": source["distinct_observation_days"]},
        )
    if attention and pending_days is not None:
        add(
            "pending_time",
            min(pending_days / policy["pending_full_days"], 1),
            "Tempo aguardando decisão humana" if unresolved else "Tempo da pendência operacional",
            {"days": pending_days, "since": source.get("pending_since")},
        )
    if attention and source.get("development_known"):
        if dev is None:
            factor, reason = 1, "Sem encaminhamento de desenvolvimento registrado; inclusão depende do usuário"
        elif dev["status"] == "WAITING_INFORMATION":
            factor, reason = 0.5, "Desenvolvimento aguardando informações"
        else:
            factor, reason = 0, "Desenvolvimento já registrado; nenhuma tarefa ou etapa será alterada"
        add(
            "development",
            factor,
            reason,
            {
                "item": dev.get("id") if dev else None,
                "status": dev.get("status") if dev else None,
                "days_in_status": dev_days,
            },
        )
    # Choose ONE additional fact; mirrored matching/support/new-ad alerts never earn points.
    extra = []
    if source.get("partner_status") == "Reapareceu":
        extra.append((0.5, "Anúncio reapareceu após ausência comprovada", "returned"))
    if "DECISAO_DESATUALIZADA" in source.get("alert_types", []) and source.get("decision_stale"):
        extra.append((1, "Decisão anterior exige nova conferência", "invalid_decision"))
    if attention and extra:
        factor, reason, fact = max(extra)
        add("operational_evidence", factor, reason, {"fact": fact})
    identity_warnings = set(source.get("parse_warnings", [])) - {"FILTROS_ZERO_KM_CONFLITANTES"}
    sufficient = (
        complete
        and known
        and fresh is not None
        and fresh <= policy["freshness_days"]
        and not identity_warnings
        and not unresolved
    )
    confidence = "insufficient" if not complete or not known else "sufficient" if sufficient else "partial"
    if attention and complete and fresh is not None and fresh <= policy["freshness_days"] and not identity_warnings:
        add("data_quality", 1, "Identidade preenchida e observação recente", {"days_since_seen": fresh})
    score = (
        None
        if confidence == "insufficient" or not policy["enabled"]
        else round(min(100, max(0, sum(s["points"] for s in signals))), 2)
    )
    priority = (
        "unassessed"
        if score is None
        else "high"
        if score >= policy["thresholds"]["high"]
        else "medium"
        if score >= policy["thresholds"]["medium"]
        else "low"
    )
    limitations = []
    if not complete:
        limitations.append("Identidade incompleta")
    if not known:
        limitations.append("Comparação atual com a base indisponível")
    if fresh is None or fresh > policy["freshness_days"]:
        limitations.append("Observação antiga ou sem data válida")
    if unresolved:
        limitations.append("Confirmação humana pendente")
    if identity_warnings:
        limitations.append("Avisos de interpretação da identidade")
    if not source.get("development_known"):
        limitations.append("Histórico de desenvolvimento indisponível")
    return {
        "score": score,
        "suggested_priority": priority,
        "confidence": confidence,
        "reasons": signals,
        "evidence": evidence,
        "limitations": limitations,
        "pending_days": pending_days,
        "awaiting_human": unresolved,
        "active_development": active_dev,
        "policy_version": policy["version"],
        "policy_hash": policy_hash(policy),
        "policy": policy,
        "calculated_at": now.isoformat(),
        "scanner_base_version": source.get("scanner_base_version"),
        "source_snapshot_id": source.get("source_snapshot_id"),
    }
