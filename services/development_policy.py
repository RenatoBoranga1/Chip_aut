"""Development policy is independent of scanner coverage and matching."""

import json
import os
from pathlib import Path

STATES = {
    "NEW": "Nova",
    "UNDER_ANALYSIS": "Em análise",
    "WAITING_INFORMATION": "Aguardando informações",
    "DATA_COLLECTED": "Dados coletados",
    "IN_DEVELOPMENT": "Em desenvolvimento",
    "IN_VALIDATION": "Em validação",
    "COMPLETED": "Concluída",
    "DISCARDED": "Descartada",
}
REASONS = {
    "CONFIRMED_MISSING": "Ausência confirmada na base",
    "UNSUPPORTED": "Sem suporte",
    "PARTIAL_SUPPORT": "Suporte parcial",
    "HIGH_PRIORITY_REVIEW": "Revisão de alta prioridade",
    "NEW_MODEL": "Novo modelo",
    "MANUAL": "Inclusão manual",
}
PRIORITIES = {"high": "Alta", "medium": "Média", "low": "Baixa"}
CLOSED = {"COMPLETED", "DISCARDED"}
TRANSITIONS = {
    "NEW": {"UNDER_ANALYSIS", "DISCARDED"},
    "UNDER_ANALYSIS": {"WAITING_INFORMATION", "DATA_COLLECTED", "DISCARDED"},
    "WAITING_INFORMATION": {"DATA_COLLECTED", "UNDER_ANALYSIS", "DISCARDED"},
    "DATA_COLLECTED": {"IN_DEVELOPMENT", "UNDER_ANALYSIS", "DISCARDED"},
    "IN_DEVELOPMENT": {"IN_VALIDATION", "WAITING_INFORMATION", "DISCARDED"},
    "IN_VALIDATION": {"COMPLETED", "IN_DEVELOPMENT", "DISCARDED"},
    "COMPLETED": {"UNDER_ANALYSIS"},
    "DISCARDED": {"UNDER_ANALYSIS"},
}
TECHNICAL = {
    "protocol": "Protocolo",
    "ecu": "ECU",
    "electronic_system": "Sistema eletrônico",
    "connector": "Conector",
    "cable": "Cabo",
    "technical_notes": "Observações técnicas",
    "supplier": "Fornecedor/parceiro",
    "collected_on": "Data de coleta técnica",
}
CHECKLIST = {
    "identity": "Identidade confirmada",
    "available": "Veículo disponível no parceiro",
    "information": "Informações técnicas coletadas",
    "communication": "Comunicação validada",
    "started": "Desenvolvimento iniciado",
    "tested": "Teste realizado",
    "validated": "Resultado validado",
    "updated": "Base/scanner atualizado",
}


def load_development_config(path=None):
    filename = (
        path
        or os.environ.get("MOTO_DEVELOPMENT_CONFIG")
        or Path(__file__).resolve().parents[1] / "config/development.json"
    )
    data = json.loads(Path(filename).read_text(encoding="utf-8"))
    if set(data) - {"enabled", "alerts_enabled", "stale_days", "assignees", "checklist"}:
        raise ValueError("Configuração de desenvolvimento desconhecida")
    for flag in ("enabled", "alerts_enabled"):
        if type(data.get(flag)) is not bool:
            raise ValueError("Configuração de desenvolvimento inválida")
    thresholds = data.get("stale_days", {})
    if not isinstance(thresholds, dict) or any(
        k not in STATES or k in CLOSED or type(v) is not int or not 1 <= v <= 3650 for k, v in thresholds.items()
    ):
        raise ValueError("Prazos de desenvolvimento inválidos")
    people = data.get("assignees", [])
    if not isinstance(people, list) or any(not isinstance(v, str) or not v.strip() or len(v) > 120 for v in people):
        raise ValueError("Responsáveis inválidos")
    checklist = data.get("checklist", CHECKLIST)
    if (
        not isinstance(checklist, dict)
        or len(checklist) > 30
        or any(
            not isinstance(k, str) or not k or not isinstance(v, str) or not v.strip() or len(v) > 160
            for k, v in checklist.items()
        )
    ):
        raise ValueError("Checklist inválido")
    return {**data, "checklist": checklist, "assignees": people, "stale_days": thresholds}
