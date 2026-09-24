"""Portuguese labels at the presentation boundary, with logged safe fallbacks."""

import logging
import re

LOGGER = logging.getLogger(__name__)

ALERT_TYPES = {
    "DEV_NEW": "Desenvolvimento: novo item prioritário",
    "DEV_STALE": "Desenvolvimento: acompanhar prazo",
    "DEV_VALIDATION": "Desenvolvimento: em validação",
    "DEV_COMPLETED": "Desenvolvimento: concluído",
    "NOVO_ANUNCIO": "Novo anúncio",
    "POSSIVEL_NOVA_MOTO": "Possível nova moto",
    "SEM_SUPORTE": "Sem suporte",
    "SUPORTE_PARCIAL": "Suporte parcial",
    "REVISAO_ALTA_PRIORIDADE": "Revisão de alta prioridade",
    "DECISAO_DESATUALIZADA": "Decisão desatualizada",
    "FALHA_COLETA": "Falha de coleta",
    "FALHA_PIPELINE": "Falha de atualização",
    "COLETA_PARCIAL": "Coleta incompleta ou com avisos",
    "NOVA_VERSAO_BASE": "Nova versão da base",
}
ALERT_SEVERITIES = {"INFO": "Informativo", "ATENCAO": "Atenção", "ALTA": "Alta prioridade", "CRITICA": "Crítico"}
ALERT_STATES = {"NOVO": "Novo", "LIDO": "Lido", "ARQUIVADO": "Arquivado", "RESOLVIDO": "Resolvido"}
ALERT_ACTIONS = {
    "CRIADO": "Criado",
    "LIDO": "Lido",
    "NAO_LIDO": "Marcado como não lido",
    "ARQUIVADO": "Arquivado",
    "RESOLVIDO": "Resolvido",
    "REABERTO": "Reaberto",
    "CONDICAO_ENCERRADA": "Condição deixou de ser observada",
}

LABELS = {
    "id": "Revisão",
    "manufacturer": "Fabricante",
    "model": "Modelo",
    "version": "Versão",
    "year": "Ano",
    "partner": "Parceiro",
    "priority": "Prioridade",
    "state": "Situação da revisão",
    "automatic_type": "Resultado automático",
    "effective_type": "Resultado considerado pelo sistema",
    "score": "Pontuação de similaridade",
    "coverage": "Cobertura",
    "last_seen": "Última aparição",
    "external_id": "Identificador do anúncio",
    "source_url": "Link do anúncio",
    "scanner_key": "Chave da base",
    "price": "Preço (R$)",
    "mileage": "Quilometragem",
    "supported_systems": "Sistemas suportados",
    "unsupported_systems": "Sistemas sem suporte",
    "analysis_systems": "Sistemas em análise",
    "unknown_systems": "Sistemas sem situação definida",
    "evidence": "Evidência",
    "status": "Situação",
    "system_count": "Sistemas",
    "latest_date": "Data relevante",
    "confidence": "Pontuação de similaridade",
    "scanner_status": "Situação da cobertura",
    "key": "Chave da base",
    "first_seen": "Primeira aparição",
    "first_seen_at": "Primeira aparição",
    "last_seen_at": "Última aparição",
    "reviewer": "Revisor",
    "note": "Justificativa",
    "action": "Ação",
    "created_at": "Data e hora",
    "updated_at": "Última atualização",
    "import_id": "Versão da base",
    "run_id": "Execução",
    "collection_id": "Coleta",
    "review_item_id": "Item de revisão",
    "previous_decision_id": "Decisão anterior",
    "before_state": "Situação anterior",
    "after_state": "Nova situação",
    "decision_id": "Decisão",
    "reasons": "Explicações",
    "reason": "Motivo",
    "blockers": "Impedimentos",
    "components": "Composição da pontuação",
    "token_sort": "Similaridade sem considerar a ordem",
    "token_set": "Similaridade das palavras em comum",
    "compact": "Similaridade do nome sem espaços",
    "new": "Novos anúncios",
    "reappeared": "Anúncios reencontrados",
    "disappeared": "Anúncios que deixaram de aparecer",
    "memory_scope": "Abrangência da decisão",
    "policy": "Regras aplicadas",
    "normalized_identity": "Identidade padronizada",
    "raw_name": "Nome original",
    "raw_text": "Texto original",
    "match_type": "Resultado da correspondência",
    "release_labels": "Indicações de lançamento",
    "system_names": "Sistemas registrados",
    "record_count": "Registros de origem",
    "source_rows": "Linhas de origem",
    "raw_models": "Modelos na origem",
    "errors": "Falhas",
    "warnings": "Avisos",
    "metadata": "Informações da coleta",
    "code": "Motivo",
    "detail": "Descrição",
    "page": "Página",
    "scope": "Filtro consultado",
}

VALUES = {
    "pending": "Pendente",
    "resolved": "Resolvido",
    "ignored": "Ignorado",
    "deferred": "Adiado",
    "invalidated": "Precisa de nova revisão",
    "reused": "Reaproveitado",
    "high": "Alta",
    "medium": "Média",
    "low": "Baixa",
    "EXATO_NORMALIZADO": "Correspondência exata",
    "EXACT": "Correspondência exata",
    "CORRESPONDENCIA_PROVAVEL": "Correspondência provável",
    "REVISAR": "Revisar",
    "REVIEW": "Revisar",
    "AMBIGUOUS": "Ambíguo",
    "AMBIGUO": "Ambíguo",
    "NOT_FOUND": "Não encontrado na base",
    "NAO_ENCONTRADA_NA_BASE": "Não encontrado na base",
    "CONFIRMADO_AUSENTE_NA_BASE": "Ausência confirmada na base atual",
    "EXATO_CONFIRMADO_HUMANAMENTE": "Correspondência confirmada pelo revisor",
    "CONFIRMADO_MANUALMENTE": "Correspondência confirmada pelo revisor",
    "AGUARDANDO_MATCHING": "Aguardando comparação com a base",
    "IDENTIDADE_PENDENTE": "Identidade em revisão",
    "PROVAVELMENTE_NAO_SUPORTADA_NA_BASE": "Provável ausência na base",
    "SUPORTADO": "Suportado",
    "SEM_SUPORTE": "Sem suporte",
    "SUPORTE_PARCIAL": "Suporte parcial",
    "EM_ANALISE": "Em análise",
    "SEM_STATUS": "Situação não definida",
    "COMPLETE": "Concluída",
    "PARTIAL": "Parcial",
    "CACHED": "Dados temporários reutilizados",
    "FAILED": "Falha",
    "SUCCESS": "Sucesso",
    "WARNING": "Aviso",
    "CONFIRMAR_MATCH": "Confirmar correspondência",
    "REJEITAR_CANDIDATO": "Rejeitar candidato",
    "NAO_EXISTE_NA_BASE": "Confirmar ausência na base atual",
    "DEIXAR_PENDENTE": "Adiar",
    "IGNORAR": "Ignorar",
    "STALE_BASE_VERSION": "A base mudou; a decisão precisa de nova revisão",
    "STALE_TARGET_REMOVED_OR_CHANGED": "A moto vinculada mudou ou saiu da base; revise a decisão",
    "ADVERTISEMENT_IDENTITY_CHANGED": "A identidade do anúncio mudou; revise a nova identificação",
    "identity": "Anúncios com a mesma identidade",
    "advertisement": "Somente este anúncio",
    "FILTROS_ZERO_KM_CONFLITANTES": "Mesmos anúncios encontrados nos filtros de 0 km e usados",
    "MISSING_PRICE": "Preço não informado",
    "UNKNOWN_YEAR": "Ano não identificado",
    "INFORMACAO_NUMERICA_AUSENTE": "Faltam números para identificar o modelo ou a versão",
    "NUMEROS_DE_MODELO_OU_VERSAO_DIFERENTES": "Números do modelo ou da versão são diferentes",
    "VERSAO_DIFERENTE_OU_INCOMPLETA": "Versão diferente ou incompleta",
    "wr_motos": "WR Motos",
}
VALUES.update(
    {
        "MARCA_OU_MODELO_NAO_INTERPRETADO": "Fabricante ou modelo não identificado",
        "ANO_AMBIGUO": "Há mais de um ano possível no anúncio",
        "ANO_AUSENTE": "Ano não informado",
        "UNPARSED_CARD": "Não foi possível ler um anúncio",
        "MISSING_SCOPE": "Um dos filtros não foi coletado",
        "INCOMPLETE": "Incompleta",
        "ERROR": "Falha",
        "identity_scoped": "Anúncios com a mesma identidade",
    }
)
VALUES.update(
    {
        "RUNNING": "Em execução",
        "SUCCESS": "Concluída",
        "PARTIAL_SUCCESS": "Concluída com avisos",
        "FAILED": "Falhou",
        "SKIPPED_ALREADY_RUNNING": "Ignorada porque já havia execução ativa",
        "CANCELLED": "Cancelada",
        "DISABLED": "Desabilitado",
        "STOPPED": "Parado",
        "STALE_ACTIVITY": "Sem sinal recente de atividade",
        "CONFIG_PENDING": "Configuração aguardando aplicação",
        "manual": "Manual",
        "scheduled": "Agendada",
    }
)
LABELS.update(
    {
        "started_at": "Início",
        "finished_at": "Fim",
        "heartbeat_at": "Último sinal de atividade",
        "trigger_type": "Origem",
        "pipeline_run_id": "Execução",
        "duration_seconds": "Duração (segundos)",
        "ads_before": "Anúncios antes",
        "ads_after": "Anúncios depois",
        "error_summary": "Observação",
        "attempts": "Tentativas",
    }
)
VALUES.update(
    {
        "AccessDeniedError": "O site interrompeu o acesso; não houve tentativa de contorno",
        "Timeout": "O site demorou a responder",
        "ReadTimeout": "O site demorou a enviar a resposta",
        "ConnectTimeout": "O site demorou a aceitar a conexão",
        "ConnectionError": "Falha de conexão com o site",
        "RuntimeError": "Falha na leitura ou validação dos dados",
        "OperationalError": "Falha ao acessar o banco de dados",
    }
)
VALUES = {k.casefold(): v for k, v in VALUES.items()}
ENUM_FIELDS = {
    "state",
    "priority",
    "automatic_type",
    "effective_type",
    "coverage",
    "status",
    "scanner_status",
    "match_type",
    "action",
    "before_state",
    "after_state",
    "memory_scope",
    "scope",
    "stale_reason",
    "code",
    "trigger_type",
    "Classificação",
    "Estado",
    "Cobertura",
}
TEXT_FIELDS = {"reason", "reasons", "blockers", "evidence"}
ACTIONS = {
    VALUES[k.casefold()]: k
    for k in ("CONFIRMAR_MATCH", "REJEITAR_CANDIDATO", "NAO_EXISTE_NA_BASE", "DEIXAR_PENDENTE", "IGNORAR")
}
SORTS = {"priority": "Prioridade", "recent": "Mais recente", "oldest": "Mais antigo", "model": "Fabricante / modelo"}
ZERO_KM = "A classificação entre 0 km e usado não pôde ser determinada com segurança porque o site retornou os mesmos anúncios nos dois filtros."
IDENTITY_HELP = "Confirmar a identidade da moto não altera automaticamente a situação de suporte."
MATCH_HELP = "Indica o quanto o anúncio conseguiu ser associado a uma moto da base do scanner."
COVERAGE_HELP = "Indica a situação de suporte da moto na base atual do scanner."


def label(key):
    if key in LABELS:
        return LABELS[key]
    if key in {
        "Quantidade de falhas",
        "Quantidade de avisos",
        "Classificação",
        "Anúncios",
        "Estado",
        "Itens",
        "Cobertura",
        "Páginas",
        "Total bruto",
        "Duplicados",
        "Total líquido",
        "Falhas",
        "Avisos na leitura dos anúncios",
        "Ocorrências",
        "Coleta",
        "Data",
    }:
        return key  # Already authored Portuguese column caption.
    LOGGER.warning("ui_untranslated_field key=%s", key)
    return "Informação adicional"


def value(raw):
    if raw is None:
        return "Não informado"
    translated = VALUES.get(str(raw).casefold())
    if translated:
        return translated
    LOGGER.warning("ui_untranslated_value value=%s", raw)
    return "Informação ainda sem tradução"


def explanation(raw):
    """Translate generated explanations, never original advertisement text or reviewer notes."""
    text = str(raw)
    for token, translated in sorted(VALUES.items(), key=lambda pair: len(pair[0]), reverse=True):
        text = re.sub(r"(?<![\w])" + re.escape(token) + r"(?![\w])", lambda _: translated, text, flags=re.I)
    replacements = {
        "score": "pontuação de similaridade",
        "matching": "correspondência",
        "reviewer": "revisor",
        "tokens": "palavras e números",
        "token_sort": "comparação sem considerar a ordem",
        "aliases": "nomes equivalentes",
        "fuzzy": "aproximada",
        "status": "situação",
    }
    for token, translated in replacements.items():
        text = re.sub(r"\b" + token + r"\b", translated, text, flags=re.I)
    return re.sub(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", lambda m: value(m[0]), text)


def cell(field, raw):
    if field == "error_summary" and raw:
        return "Há observações; consulte os detalhes da execução"
    if raw is None:
        return "Não informado"
    if isinstance(raw, bool):
        return "Sim" if raw else "Não"
    if isinstance(raw, dict):
        return "; ".join(f"{label(k)}: {cell(k, v)}" for k, v in raw.items()) or "Nenhum registro"
    if isinstance(raw, (tuple, list)):
        return "; ".join(str(cell(field, v)) for v in raw) or "Nenhum registro"
    if field in ENUM_FIELDS:
        return value(raw)
    if field == "partner":
        return VALUES.get(str(raw).casefold(), str(raw))  # Partner names are source data.
    if field in TEXT_FIELDS:
        return explanation(raw)
    return raw


def row_labels(row):
    result = {}
    for n, (key, raw) in enumerate(row.items(), 1):
        name = label(key)
        if name in result:
            name += f" ({n})"
        result[name] = cell(key, raw)
    return result


def validation_message(error):
    text = str(error)
    known = {
        "Ação, reviewer e justificativa são obrigatórios": "Informe a ação, o revisor e a justificativa.",
        "Candidato obrigatório somente para confirmar/rejeitar": "Selecione um candidato para confirmar ou rejeitar.",
    }
    if text in known:
        return known[text]
    # Domain validations are Portuguese; unknown technical errors stay in the local log.
    if text.startswith(
        (
            "Item ",
            "Anúncio ",
            "A identidade ",
            "Identidade ",
            "Candidato ",
            "Identificador ",
            "Dashboard ",
            "Submissão ",
        )
    ):
        return explanation(text).replace("Dashboard", "Painel")
    LOGGER.warning("ui_untranslated_error error=%s", text)
    return "Não foi possível salvar. Atualize o item e confira os dados antes de tentar novamente."
