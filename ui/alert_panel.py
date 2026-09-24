"""Portuguese alert center. Detection rules remain in the service layer."""

import logging

import streamlit as st

from services.alert_service import AlertService, filter_alerts
from ui.textos import ALERT_ACTIONS, ALERT_SEVERITIES, ALERT_STATES, ALERT_TYPES, LABELS, cell, explanation, value
from ui.vehicle_images import vehicle_photo


def navigate(page, field=None, identifier=None):
    st.session_state.navigation = page
    if field:
        st.session_state[field] = identifier


def alert_center(dashboard):
    service = AlertService(dashboard.config)
    snapshot = service.snapshot()
    rows = snapshot["alerts"]
    if snapshot["pending"]:
        st.warning(
            f"{snapshot['pending']} execução(ões) com geração de alertas pendente. A próxima atualização tentará novamente."
        )
    cols = st.columns(5)
    for col, label, count in zip(
        cols,
        ["Novos", "Alta prioridade", "Críticos", "Não lidos", "Arquivados"],
        [
            sum(r["status"] == "NOVO" for r in rows),
            sum(r["severity"] == "ALTA" and r["status"] in {"NOVO", "LIDO"} for r in rows),
            sum(r["severity"] == "CRITICA" and r["status"] in {"NOVO", "LIDO"} for r in rows),
            sum(r["status"] == "NOVO" for r in rows),
            sum(r["status"] == "ARQUIVADO" for r in rows),
        ],
    ):
        col.metric(label, count)
    with st.expander("Filtros de alertas", expanded=True):
        filters = {}
        filter_columns = st.columns(3)
        for index, (key, label, mapping) in enumerate(
            [
                ("status", "Situação do alerta", ALERT_STATES),
                ("severity", "Prioridade do alerta", ALERT_SEVERITIES),
                ("alert_type", "Tipo de alerta", ALERT_TYPES),
            ]
        ):
            filters[key] = filter_columns[index].multiselect(
                label, list(mapping), format_func=mapping.get, key="alerts_" + key, placeholder="Todos"
            )
        filters["manufacturer"] = filter_columns[0].multiselect(
            "Fabricante",
            sorted({r["manufacturer"] for r in rows if r["manufacturer"]}),
            key="alerts_manufacturer",
            placeholder="Todos",
        )
        filters["partner"] = filter_columns[1].multiselect(
            "Parceiro do alerta",
            sorted({r["partner"] for r in rows}),
            format_func=lambda v: cell("partner", v),
            placeholder="Todos",
        )
        start = filter_columns[0].date_input("Última ocorrência a partir de", value=None, format="DD/MM/YYYY")
        end = filter_columns[1].date_input("Última ocorrência até", value=None, format="DD/MM/YYYY")
        read = filter_columns[2].selectbox("Leitura", ["Todos", "Não lidos", "Lidos ou encerrados"])
        sorts = {
            "priority": "Prioridade, não lidos e recentes",
            "recent": "Mais recentes",
            "oldest": "Mais antigos",
            "title": "Título",
        }
        sort = filter_columns[2].selectbox("Ordenar alertas por", list(sorts), format_func=sorts.get)
    filtered = filter_alerts(rows, filters, start, end, None if read == "Todos" else read != "Não lidos", sort)
    size = 30
    page = st.selectbox("Página de alertas", range(1, max(1, (len(filtered) + size - 1) // size) + 1))
    visible = filtered[(page - 1) * size : page * size]
    if not visible:
        st.info("Nenhum alerta para esta seleção.")
        return
    st.caption(f"{len(filtered)} alertas · horários registrados em UTC")
    st.table(
        [
            {
                "Alerta": r["id"] if r["id"] > 0 else f"Desenvolvimento {abs(r['id'])}",
                "Prioridade": ALERT_SEVERITIES[r["severity"]],
                "Data": r["created_at"],
                "Título": r["title"],
                "Tipo": ALERT_TYPES[r["alert_type"]],
                "Parceiro": cell("partner", r["partner"]),
                "Moto": r["details"].get("advertisement", {}).get("raw_name", "—"),
                "Situação": ALERT_STATES[r["status"]],
                "Última ocorrência": r["last_seen_at"],
            }
            for r in visible
        ]
    )
    selected = st.selectbox(
        "Abrir alerta",
        [None, *[r["id"] for r in visible]],
        format_func=lambda n: (
            (f"Alerta #{n}" if n > 0 else f"Desenvolvimento #{abs(n)}") if n else "Selecione um alerta"
        ),
        key="alert_selection",
    )
    if selected is None:
        return
    item = next(r for r in visible if r["id"] == selected)
    details = item["details"]
    st.subheader(item["title"])
    st.write(item["message"])
    st.caption("Evidência da ocorrência registrada; a cobertura atual pode ter mudado desde então.")
    st.write(
        f"Primeira ocorrência: {item['first_seen_at']} · Última ocorrência: {item['last_seen_at']} · Ocorrências: {item['occurrence_count']}"
    )
    st.write(f"Situação: {ALERT_STATES[item['status']]} · Prioridade: {ALERT_SEVERITIES[item['severity']]}")
    if not item["condition_active"]:
        st.info("Esta condição deixou de ser observada. O histórico permanece disponível.")
    ad = details.get("advertisement", {})
    from ui.development_panel import offer_creation, open_item

    if details.get("development_item_id"):
        st.button("Abrir item de desenvolvimento", on_click=open_item, args=(details["development_item_id"],))
    elif ad:
        offer_creation(dashboard, "alert", selected, f"alert_{selected}")
    if ad:
        photo_ad = {**ad, **dashboard.image_metadata(ad)}
        vehicle_photo(photo_ad, details, detail=True, alert_type=item["alert_type"])
        if photo_ad.get("primary_image_url"):
            st.caption("Foto da observação mais recente deste anúncio; a evidência do alerta permanece histórica.")
        st.write(
            f"{ad.get('manufacturer') or 'Fabricante não informado'} · {ad.get('model') or 'Modelo não informado'} · Ano {ad.get('year') or 'não informado'}"
        )
        st.write("Correspondência: " + value(details.get("matching")))
        st.write(
            "Cobertura: "
            + (value(details.get("coverage")) if details.get("coverage") else "Identidade sem suporte confirmado")
        )
        if ad.get("source_url", "").startswith(("https://", "http://")):
            st.link_button("Abrir anúncio", ad["source_url"])
    for key, systems in details.get("systems", {}).items():
        st.write(f"{LABELS[key]}: {', '.join(systems) or 'Nenhum registro'}")
    if details.get("evidence"):
        st.write(details["evidence"])
    if details.get("decision_id"):
        st.write(f"Decisão anterior #{details['decision_id']}: {value(details['decision'])}")
        st.write(explanation(details["reason"]))
    if details.get("base_id"):
        st.write(
            f"Versão da base: {details['base_id']} · Versão anterior: {details.get('old_base_id') or 'Não se aplica'}"
        )
    if details.get("stage"):
        st.write(
            "Etapa: "
            + {"collection": "Coleta", "publication": "Publicação da atualização", "preflight": "Preparação"}.get(
                details["stage"], "Atualização"
            )
        )
        st.write(details["error"])
        st.write(
            f"Tentativas: {details.get('attempts', 0)} · Falhas consecutivas: {details.get('consecutive_failures', 0)}"
        )
        st.write("Próxima atualização prevista na ocasião: " + (details.get("next_run_at") or "Sem previsão ativa"))
    if "published" in details:
        st.write(
            "Dados publicados com avisos."
            if details["published"]
            else "Coleta incompleta: dados anteriores preservados."
        )
        for warning, count in details.get("warnings", {}).items():
            st.write(f"{value(warning)}: {count}")
    if item["pipeline_run_id"]:
        st.caption(
            f"Execução {item['pipeline_run_id']} · Coleta {item['collection_run_id'] or 'Não publicada'} · Anúncio {item['external_id'] or 'Não se aplica'}"
        )
    if item["review_item_id"]:
        st.button(
            "Abrir item na fila",
            on_click=navigate,
            args=("Fila de revisão", "related_review_id", item["review_item_id"]),
        )
    if item["pipeline_run_id"]:
        st.button(
            "Abrir execução relacionada",
            on_click=navigate,
            args=("Atualização automática", "related_pipeline_id", item["pipeline_run_id"]),
        )
    st.caption("Estas ações alteram somente o alerta. Não modificam correspondência, cobertura ou decisões humanas.")
    actions = (
        [("Marcar como lido", "LIDO"), ("Marcar como não lido", "NOVO")]
        if item["status"] in {"NOVO", "LIDO"}
        else [("Reabrir", "NOVO")]
    )
    actions += [("Arquivar", "ARQUIVADO"), ("Resolver", "RESOLVIDO")]
    for label, target in actions:
        if st.button(
            label, disabled=dashboard.config.read_only or target == item["status"], key="alert_action_" + target
        ):
            try:
                service.transition(selected, target)
            except Exception:
                logging.getLogger(__name__).exception("Falha ao alterar alerta")
                st.error("Não foi possível alterar o alerta. Atualize e confira o histórico.")
            else:
                st.rerun()
    st.subheader("Histórico do alerta")
    st.table(
        [
            {
                "Data": h["created_at"],
                "Ação": ALERT_ACTIONS[h["action"]],
                "Situação anterior": ALERT_STATES.get(h["before_status"], "—"),
                "Nova situação": ALERT_STATES[h["after_status"]],
            }
            for h in service.history(selected)
        ]
    )
