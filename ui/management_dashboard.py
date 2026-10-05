"""Read-only management UI. All definitions and queries live outside Streamlit."""

import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

import pandas as pd
import streamlit as st

from services.development_policy import STATES
from services.management_metrics_service import (
    DEFINITIONS,
    FILTERS,
    ZONE,
    ManagementMetricsService,
    csv_export,
    distribution,
    period,
)
from ui.textos import LABELS as FIELD_LABELS
from ui.textos import VALUES

LABELS = {
    "manufacturer": "Fabricante",
    "model": "Modelo",
    "year": "Ano",
    "base_status": "Situação na base",
    "human_status": "Estado humano",
    "development_stage": "Etapa de desenvolvimento",
    "priority": "Prioridade operacional",
    "assigned_to": "Responsável",
}


def portuguese(value):
    if isinstance(value, dict):
        return {FIELD_LABELS.get(k, k): portuguese(v) for k, v in value.items()}
    if isinstance(value, list):
        return [portuguese(v) for v in value]
    if not isinstance(value, str):
        return value
    if value in STATES:
        return STATES[value]
    if value.casefold() in VALUES:
        return VALUES[value.casefold()]
    pattern = r"\b(?:[A-Z]+_[A-Z_]+|Matching|matching|pending|deferred|invalidated|COMPLETED|DISCARDED)\b"
    return re.sub(
        pattern,
        lambda m: (
            "Comparação automática"
            if m[0].lower() == "matching"
            else STATES.get(m[0], VALUES.get(m[0].casefold(), m[0]))
        ),
        value,
    )


def frame(rows, key):
    if not rows:
        st.info("Sem registros para este recorte.")
        return
    size = 30
    page = st.number_input(
        "Página", min_value=1, max_value=max(1, (len(rows) + size - 1) // size), value=1, key=key + "_page"
    )
    st.caption(f"{len(rows)} registros · até {size} por página")
    st.dataframe(portuguese(rows[(page - 1) * size : page * size]), hide_index=True, width="stretch")


def bars(rows, field, title):
    st.subheader(portuguese(title))
    data = portuguese(distribution(rows, field))
    if data:
        st.bar_chart(pd.DataFrame(data).set_index("Categoria"))
    else:
        st.caption("Sem dados para este gráfico.")


def trend(rows, title):
    st.subheader(portuguese(title))
    if not rows:
        st.caption("Sem avaliações/eventos neste período; lacunas não são zeros.")
        return
    data = pd.DataFrame(portuguese(rows))
    if "Base" in data:
        data["Categoria"] = data["Categoria"] + " · base " + data["Base"].astype(str)
    chart = data.pivot_table(index="Data", columns="Categoria", values="Quantidade", aggfunc="sum")
    st.line_chart(chart)
    with st.expander("Ver pontos do gráfico"):
        st.dataframe(data, hide_index=True)


def management_page(service):
    analytics = ManagementMetricsService(service.config.database, service.config.partner)
    today = datetime.now(ZONE).date()
    st.caption("Consulta gerencial somente leitura · fuso America/Sao_Paulo · parceiro escolhido na barra lateral.")
    preset = st.selectbox(
        "Período",
        ["Hoje", "Últimos 7 dias", "Últimos 30 dias", "Últimos 90 dias", "Ano atual", "Personalizado"],
        index=2,
    )
    custom = (
        st.date_input("Datas do período", (today - timedelta(days=29), today), max_value=today)
        if preset == "Personalizado"
        else None
    )
    try:
        start, end = period(preset, today, custom)
    except ValueError as exc:
        st.warning(str(exc))
        return
    versions = analytics.repository.versions()
    version = st.selectbox(
        "Versão da base",
        [None, *[r["id"] for r in versions]],
        format_func=lambda v: "Vigente no fim de cada período" if v is None else f"Base {v}",
    )
    unfiltered = analytics.report(start, end, version=version)
    with st.expander("Filtros gerenciais"):
        with st.form("management_filters"):
            columns = st.columns(2)
            filters = {}
            for i, field in enumerate(FILTERS):
                options = sorted(
                    {
                        str(r.get(field) if r.get(field) is not None else "Não informado")
                        for r in [*unfiltered["all_rows"], *unfiltered["development"]]
                    }
                )
                with columns[i % 2]:
                    filters[field] = st.multiselect(
                        LABELS[field], options, format_func=portuguese, key="management_" + field
                    )
            st.form_submit_button("Aplicar filtros")
    report = analytics.report(start, end, filters, version)
    st.caption(
        f"De {start:%d/%m/%Y} a {end:%d/%m/%Y} · base {report['base_id'] or 'indisponível'} · corte: {report['cutoff']} · cálculo: {report['elapsed_seconds']:.3f} s"
    )
    st.info(
        "Novo anúncio, não encontrado automaticamente e ausência confirmada são conceitos distintos. Cards de situação mostram o encerramento; cards de eventos contam ocorrências no período. Clique em um indicador para abrir sua lista abaixo."
    )
    if not report["base_id"]:
        st.warning("Não há publicação da base selecionada anterior ao encerramento deste período.")
    if not report["availability"]["priorities"]:
        st.caption(
            "Priorização operacional indisponível neste banco: nenhum cálculo ou migração é executado pela consulta."
        )
    if st.checkbox("Comparar indicadores por parceiro", key="management_by_partner"):
        from services.management_metrics_service import reports_by_partner

        comparison = reports_by_partner(service.config.database, start, end, filters=filters, version=version)
        st.dataframe(comparison["partners"], hide_index=True)
        st.caption(
            f"{comparison['occurrences']} anúncios · {comparison['identity_groups']} identidades estritas ou casos isolados. Identidades não são somadas entre parceiros; ambiguidades permanecem separadas."
        )
    executive = [
        "Novos anúncios",
        "Possíveis novas identidades",
        "Ausências confirmadas no período",
        "Revisões pendentes",
        "Revisões concluídas no período",
        "Desenvolvimentos ativos",
        "Alertas relevantes",
        "Cobertura conhecida",
    ]
    comparisons = {r["Indicador"]: r for r in report["comparisons"]}
    for offset in (0, 4):
        for column, name in zip(st.columns(4), executive[offset : offset + 4]):
            with column:
                delta = comparisons[name]["Variação"]
                st.metric(name, report["metrics"][name], help=portuguese(DEFINITIONS[name]))
                st.caption(
                    ("↑ " if delta > 0 else "↓ " if delta < 0 else "= ") + str(abs(delta)) + " em relação ao anterior"
                )
                st.button(
                    "Ver lista",
                    key="metric_" + name,
                    on_click=lambda n=name: st.session_state.update(management_detail=n),
                )
    operation, development, coverage, alerts, details = st.tabs(
        ["Revisão e demanda", "Desenvolvimento", "Cobertura e base", "Prioridades e alertas", "Detalhes e exportação"]
    )
    with operation:
        st.subheader("Comparação entre períodos")
        st.caption(
            f"Anterior: {report['previous_start']} até {report['previous_end']} (fim exclusivo). Mesma duração transcorrida; base anterior {report['previous_base_id'] or 'indisponível'}. Variação percentual vazia quando o anterior é zero."
        )
        st.dataframe(portuguese(report["comparisons"]), hide_index=True)
        st.subheader("Tempo até a primeira conclusão de revisão")
        st.table(
            [{"Período": "Atual", **report["review_time"]}, {"Período": "Anterior", **report["previous_review_time"]}]
        )
        a, b = report["review_time"]["média em dias"], report["previous_review_time"]["média em dias"]
        if a is not None and b is not None:
            st.caption(f"Variação da média: {'↑' if a > b else '↓' if a < b else '='} {abs(a - b):.3f} dias.")
        st.dataframe(report["human_distribution"], hide_index=True)
        st.subheader("Taxas com denominadores explícitos")
        st.dataframe(portuguese(report["rates"]), hide_index=True)
        left, right = st.columns(2)
        with left:
            bars(report["stock"], "automatic_type", "Matching automático no encerramento")
            bars(report["details"]["Ausências confirmadas acumuladas"], "manufacturer", "Ausências por fabricante")
            bars(report["details"]["Revisões pendentes"], "manufacturer", "Fabricantes com mais pendências")
        with right:
            bars(report["stock"], "human_status", "Decisão humana no encerramento")
            bars(report["details"]["Ausências confirmadas acumuladas"], "year", "Ausências por ano")
            bars(
                report["details"]["Ausências confirmadas acumuladas"],
                "pending_origin",
                "Origem das ausências confirmadas",
            )
        trend(report["human_series"], "Decisões humanas registradas por dia")
        trend(report["matching_series"], "Matching avaliado por dia e versão")
        st.subheader("Identidades recorrentes em anúncios distintos")
        st.caption("Identidade estrita inclui versão e ano. Recoletas do mesmo ID não aumentam esta contagem.")
        frame(report["recurrence"], "management_recurrence")
    with development:
        st.subheader("Itens por etapa no encerramento")
        st.bar_chart(pd.DataFrame(report["development_distribution"]).set_index("Etapa"))
        st.subheader("Duração das etapas encerradas no período")
        st.caption(
            "Dias corridos por passagem; inclui o tempo anterior ao início do período. Etapas abertas aparecem na lista de parados, sem entrar na média de etapas encerradas."
        )
        st.table(report["stage_times"])
        st.subheader("Tempo da criação até conclusão de desenvolvimento")
        st.table([report["development_time"]])
        st.subheader("10 itens com mais tempo na etapa")
        fields = (
            "id",
            "manufacturer",
            "model",
            "year",
            "development_stage",
            "days_in_stage",
            "assigned_to",
            "priority",
            "updated_at",
            "sla_days",
            "overdue",
        )
        frame([{k: r.get(k) for k in fields} for r in report["stalled"]], "management_stalled")
        st.caption(
            f"{len(report['overdue'])} itens excedem os prazos já configurados. Etapas sem prazo não recebem SLA inventado."
        )
        if report["development"]:
            item_id = st.selectbox("Abrir desenvolvimento existente", [None, *[r["id"] for r in report["development"]]])
            if item_id and st.button("Ver item de desenvolvimento"):
                from ui.development_panel import open_item

                open_item(item_id)
                st.rerun()
    with coverage:
        trend(report["coverage_series"], "Cobertura registrada nas avaliações")
        st.caption(
            "Última avaliação por dia, base e anúncio. Uma mesma moto pode aparecer em dias diferentes; não somar a série como demanda. Ausência humana histórica não é ausência válida na base atual."
        )
        bars(report["stock"], "coverage", "Cobertura no estoque ao encerrar")
        st.subheader("Base do scanner selecionada")
        st.caption(
            "Estatísticas da base usam apenas fabricante, modelo e ano. Responsável, prioridade e estados operacionais pertencem ao parceiro e não filtram a base global."
        )
        st.metric("Motos na base (filtros de identidade)", len(report["base"]))
        bars(report["base"], "status", "Cobertura da base selecionada")
        st.table([report["base_stats"]])
        st.caption(
            "Adições, remoções e alterações comparam com a publicação anterior. Na primeira base, todas são adições. Revalidações não são novas decisões; os contadores de publicação são globais, enquanto decisões válidas respeitam o recorte operacional."
        )
    with alerts:
        left, right = st.columns(2)
        with left:
            bars(report["stock"], "priority", "Prioridade operacional no encerramento")
            bars(
                [r for r in report["stock"] if r["priority"] != "Não avaliada"],
                "manual_priority",
                "Intervenção manual de prioridade",
            )
            bars(report["alerts"], "severity", "Severidade dos alertas")
        with right:
            bars(report["alerts"], "status", "Estado dos alertas no encerramento")
            bars(report["alerts"], "alert_type", "Tipos de alerta")
        st.caption(
            "Alertas deduplicados por origem e ID; eventos repetidos não aumentam a contagem. Filtros de veículo excluem alertas gerais sem vínculo correspondente."
        )
    with details:
        st.download_button(
            "Exportar indicadores em CSV",
            csv_export(report),
            file_name=f"indicadores_{start}_{end}.csv",
            mime="text/csv",
        )
        st.caption(
            "CSV agregado com período, versão, filtros e definição; sem nomes de revisores, justificativas ou dados pessoais de anúncios."
        )
        with st.expander("Dicionário das métricas"):
            st.table([{"Indicador": k, "Definição": portuguese(v)} for k, v in DEFINITIONS.items()])
    st.subheader("Lista do indicador")
    name = st.selectbox("Indicador para detalhar", list(DEFINITIONS), key="management_detail")
    st.caption(portuguese(DEFINITIONS[name]))
    rows = report["details"][name]
    fields = (
        "id",
        "review_item_id",
        "external_id",
        "manufacturer",
        "model",
        "year",
        "human_status",
        "base_status",
        "coverage",
        "priority",
        "development_stage",
        "created_at",
        "decision_at",
        "status",
        "alert_type",
    )
    visible = [{k: r[k] for k in fields if k in r} for r in rows]
    frame(visible, "management_detail_" + name)
    review_ids = sorted(
        {
            r.get("review_item_id") or r.get("id")
            for r in rows
            if r.get("external_id") and r.get("id") and "development_stage" in r and "state" in r
        }
    )
    if review_ids:
        selected = st.selectbox("Revisão relacionada", review_ids)
        st.link_button(
            "Ver revisão existente", "?" + urlencode({"review": selected, "partner": service.config.partner})
        )
