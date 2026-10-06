"""Read-only quality evidence, kept distinct from published inventory and decisions."""

import streamlit as st

from partners.assessments import unintegrated
from partners.diagnostics import notices
from partners.registry import PartnerRegistry
from services.partner_service import partner_status


def validation_notices(registry=None):
    rows = notices(unintegrated(registry or PartnerRegistry()))
    if rows:
        with st.expander("Avisos de validação dos parceiros"):
            st.caption(
                "Última avaliação manual; um aviso por parceiro e motivo. Sem notificações ou eventos duplicados."
            )
            st.table(rows)


def classification_panel(database, registry=None):
    st.subheader("Qualidade da classificação por parceiro")
    st.caption(
        "Diagnóstico não é estoque. Desconhecidos não foram publicados; valores não medidos aparecem como não avaliados. Nenhuma consulta aos sites é feita ao abrir esta tela."
    )
    rows = partner_status(database, registry, include_candidates=True)
    st.dataframe(
        [
            {
                "Parceiro": r["display_name"],
                "Escopo": r["metric_scope"],
                "Anúncios ativos": r["active_ads"],
                "Motos publicadas": r["valid_motorcycles"],
                "Itens observados no diagnóstico": r["observed_items"],
                "Ignorados por tipo": r["excluded_by_type"],
                "Tipo desconhecido": r["unknown_items"],
                "Falhas de classificação": r["classification_failures"],
                "Erros de diagnóstico": r["diagnostic_errors"],
                "Coleta parcial": "Sim" if r["partial"] else "Não" if r["last_collection"] else "Sem coleta",
            }
            for r in rows
        ],
        hide_index=True,
    )
    validation_notices(registry)
