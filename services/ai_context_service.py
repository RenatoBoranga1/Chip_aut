"""Explicit intent, calendar periods and bounded conversation state."""

import re
from datetime import datetime, timedelta

from scanner_base.normalizer import normalize_text
from services.management_metrics_service import ZONE

INTENTS = (
    "SCANNER_LOOKUP",
    "APPLICATION_LOOKUP",
    "CABLE_LOOKUP",
    "REVIEW_LOOKUP",
    "PARTNER_LOOKUP",
    "DEVELOPMENT_LOOKUP",
    "PRIORITIZATION_LOOKUP",
    "MANAGEMENT_METRICS",
    "ALERT_LOOKUP",
    "BASE_VERSION_LOOKUP",
    "RECENT_CHANGES",
    "GENERAL_HELP",
    "UNKNOWN",
)


def identify_intent(question):
    q = normalize_text(question)
    rules = (
        ("PARTNER_LOOKUP", r"PARCEIR|THOMAS|MOTONIL|MARQUES|WR MOTOS"),
        ("BASE_VERSION_LOOKUP", r"VERSOES|VERSAO DA BASE|BASE ATIVA|BASE V16"),
        ("MANAGEMENT_METRICS", r"RESUM|COMPARE|QUANTAS REVISOES|QUANTAS AUSENCIAS|TEMPO MEDIO|INDICADOR"),
        ("PRIORITIZATION_LOOKUP", r"PRIORIDA|PONTUACAO"),
        ("DEVELOPMENT_LOOKUP", r"DESENVOLVIMENTO|AGUARDAM INFORMAC|EM VALIDACAO|PARADAS"),
        ("ALERT_LOOKUP", r"ALERTA"),
        ("REVIEW_LOOKUP", r"REVISAO|REVISOES|AGUARDAM DECISAO|DECISAO HUMANA|CONFIRMADA|NAO FOI ENCONTRADA|MATCHING"),
        ("RECENT_CHANGES", r"ANUNCIO|APARECERAM|REAPARECERAM|ESTOQUE|MUDANCAS RECENTES"),
        ("CABLE_LOOKUP", r"CABO|CONECTOR"),
        ("APPLICATION_LOOKUP", r"SISTEMA|APLICAC|IMOBILIZADOR|VIDEO|FIPE|FUNCOES"),
        ("SCANNER_LOOKUP", r"VEICULO|MOTO|MOSTRE|BMW|HONDA|YAMAHA|TIGER|SCANNER"),
        ("GENERAL_HELP", r"AJUDA|COMO USAR|O QUE VOCE|DIFERENCA"),
    )
    for intent, pattern in rules:
        if re.search(r"\b(?:" + pattern + ")", q):
            return intent
    return "UNKNOWN"


def selected_period(question, today=None):
    today = today or datetime.now(ZONE).date()
    q = normalize_text(question)
    start = end = today
    if "ONTEM" in q:
        start = end = today - timedelta(days=1)
    elif "ESTA SEMANA" in q:
        start = today - timedelta(days=today.weekday())
    elif "MES PASSADO" in q:
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    elif "ESTE MES" in q:
        start = today.replace(day=1)
    elif "ESTE ANO" in q:
        start = today.replace(month=1, day=1)
    elif "7 DIAS" in q:
        start = today - timedelta(days=6)
    elif "30 DIAS" in q or "HOJE" not in q:
        start = today - timedelta(days=29)
    return start, end


STOP_WORDS = set(
    "MOSTRE MOSTRAR BUSQUE BUSCAR ENCONTRE QUAIS QUAL QUANTOS QUANTAS EXISTEM EXISTE TEM POSSUI "
    "INFORMACAO REGISTRADA PARA DE DA DO NA NO BASE ATIVA SCANNER VEICULO VEICULOS MOTO MOTOS "
    "SISTEMA SISTEMAS APLICACAO APLICACOES CABO CABOS USA USAM UTILIZA UTILIZAM USADO UTILIZADO NESTA NESTE ESSA ESSE ESTA "
    "DESTA DESSE ELA ELE E O A OS AS UM UMA EM COM SOBRE VIDEO FIPE IMOBILIZADOR FUNCOES AVANCADAS "
    "DETERMINADA DETERMINADO POR FAVOR DETALHES TOTAL ME INFORME INFORMACOES DESSA DESTE QUE SAO AS E".split()
)


def vehicle_terms(question):
    q = re.sub(r"\b(?:VEICULO|ID)\s*#?\s*\d+", "", normalize_text(question))
    return [w for w in re.findall(r"[A-Z0-9]+", q) if w not in STOP_WORDS][:12]


def new_conversation():
    return {"messages": [], "selected_vehicle_id": None, "selected_base_id": None, "choices": [], "scope": None}


def remember(state, question, answer, config):
    state["messages"].extend([{"role": "user", "text": question}, {"role": "assistant", "answer": answer}])
    state["messages"] = state["messages"][-config.max_history_messages :]
