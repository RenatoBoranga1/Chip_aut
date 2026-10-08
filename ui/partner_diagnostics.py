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
    alternative_sources_panel()


def alternative_sources_panel():
    from partners.sources import load_sources, source_notices

    sources = load_sources()
    names = {"thomas_motos": "Thomas Motos", "motonil": "Motonil", "moto_marques": "Moto Marques"}
    st.subheader("Fontes alternativas — avaliação M8.3")
    st.caption(
        "Evidências salvas em 08/10/2026. Nenhuma fonte aprovada; somente WR permanece ativa. Não há consultas externas nesta tela."
    )
    for source in sources:
        with st.expander(f"{names[source.partner]} — {source.source_provider} — {source.source_id}"):
            st.write("Situação: bloqueada" if source.status == "BLOCKED" else "Situação: reprovada")
            st.write(f"Fonte: {source.source_kind} · Confiança: {source.trust}")
            st.write(f"URL: {source.source_url}")
            st.write(f"Última validação: {source.source_last_validated_at}")
            st.write("Classificação segura: não aprovada")
            st.write("Campos observados: " + (", ".join(source.fields) or "Não avaliados"))
            st.write(
                f"Itens observados: {source.observed_items if source.observed_items is not None else 'Não avaliados'}"
            )
            st.write(f"Tipo desconhecido: {source.unknown if source.unknown is not None else 'Não avaliado'}")
            st.write("Amostra de ativação: não realizada; fases de acesso/classificação/identidade não aprovadas.")
            st.write(source.reason)
    with st.expander("Avisos das fontes alternativas"):
        st.caption(
            "Avisos diagnósticos deduplicados por parceiro, fonte e motivo; não geram notificações operacionais."
        )
        st.table(source_notices(sources))
