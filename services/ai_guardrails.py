"""No tools, SQL or commands are exposed to a provider. Defense in depth for input."""

import os
import re

from scanner_base.normalizer import normalize_text

READ_ONLY = "O Assistente de IA está em modo somente leitura. Essa ação exige uso da função operacional correspondente e confirmação humana."
INSUFFICIENT = "Não encontrei informação suficiente no sistema para responder com segurança."
MISSING = "Não há informação registrada para esse campo."
UNAVAILABLE = "O serviço de IA está temporariamente indisponível."
NOT_CONFIGURED = "Assistente de IA não configurado."


def redact(text):
    text = str(text)
    secret = os.environ.get("AI_API_KEY")
    if secret:
        text = text.replace(secret, "[segredo removido]")
    text = re.sub(r"(?i)\b(?:sk-[\w-]+|Bearer\s+\S+)", "[segredo removido]", text)
    text = re.sub(r"(?i)(api[_ -]?key|senha|password|token)\s*[:=]\s*\S+", r"\1=[removido]", text)
    text = re.sub(r"(?:[A-Za-z]:[\\/]|/home/|/Users/|/tmp/)[^\s]+", "[caminho removido]", text)
    return text[:2000]


def blocked(question):
    text = normalize_text(question)
    return bool(
        re.search(
            r"\b(MARQUE|MARCAR|ALTERE|ALTERAR|COLOQUE|COLOCAR|CRIE|CRIAR|PUBLIQUE|PUBLICAR|EXECUTE|EXECUTAR|"
            r"EXCLUA|EXCLUIR|APAGUE|APAGAR|HABILITE|HABILITAR|DESABILITE|CONFIRME|CONFIRMAR|CONCLUA|CONCLUIR|"
            r"MUDE|MUDAR|EDITE|EDITAR|SALVE|SALVAR|RODE|RODAR|ATUALIZE|ATUALIZAR|IGNORE|IGNORAR|"
            r"INSERT|UPDATE|DELETE|DROP|ALTER|PRAGMA|ATTACH|SELECT|SQL|POWERSHELL|SHELL|CMD|BASH|GIT|CURL)\b",
            text,
        )
        or re.search(r"https?://|\$\(|\x60", question, re.I)
    )


def validate_order(output, facts):
    """Even a malicious provider cannot invent facts, suppress evidence or issue actions."""
    if not isinstance(output, dict) or set(output) != {"fact_ids"}:
        raise ValueError("Resposta inválida")
    ids = output["fact_ids"]
    expected = [f["id"] for f in facts]
    if not isinstance(ids, list) or any(type(i) is not str for i in ids):
        raise ValueError("Referências inválidas")
    if len(ids) != len(expected) or set(ids) != set(expected):
        raise ValueError("Evidências incompletas ou inventadas")
    by_id = {f["id"]: f for f in facts}
    return [by_id[i] for i in ids]
