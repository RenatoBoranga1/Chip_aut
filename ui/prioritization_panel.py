"""Portuguese presentation only: rendering never evaluates or writes assessments."""

import json
from copy import deepcopy
from uuid import uuid4

import streamlit as st

from services.prioritization_policy import CONFIDENCE, PRIORITIES
from services.prioritization_service import PrioritizationService
from services.vehicle_image_config import load_image_config
from ui.textos import cell, value
from ui.vehicle_images import photo_cells, vehicle_photo

CRITERIA = {
    "base_status": "Situação na base",
    "recurrence": "Permanência observada",
    "pending_time": "Tempo pendente",
    "development": "Encaminhamento",
    "operational_evidence": "Evidência adicional",
    "data_quality": "Qualidade e atualidade",
}


def priority_detail(service, case_id):
    item = service.detail(case_id)
    source = item["evidence"]
    st.subheader(
        f"{source.get('manufacturer') or 'Fabricante não informado'} · {source.get('model') or 'Modelo não informado'} · {source.get('year') or 'Ano não informado'}"
    )
    vehicle_photo(source, {"development_item": True}, detail=True, force=True)
    st.write(f"Parceiro: {cell('partner', item['partner'])} · Versão: {source.get('version') or 'Não informada'}")
    st.write("Resultado automático: " + value(source.get("automatic_type")))
    st.write("Decisão humana: " + source.get("human_status", "Pendente"))
    st.write("Prioridade sugerida: **" + PRIORITIES[item["suggested_priority"]] + "**")
    st.write("Prioridade efetiva: **" + PRIORITIES[item["effective_priority"]] + "**")
    st.write("Pontuação: " + (f"{item['score']}/100" if item["score"] is not None else "Informações insuficientes"))
    st.write(CONFIDENCE[item["confidence"]] + ". Esta classificação não é uma probabilidade estatística.")
    st.caption(
        f"Última avaliação: {item['calculated_at']} · Política {item['policy_version']} · Base {item['scanner_base_version']} · Coleta {item['source_snapshot_id']}"
    )
    st.caption("Identificador da configuração: " + item["policy_hash"][:16])
    if item["manual_priority"]:
        st.info(
            f"Prioridade definida pelo usuário: {PRIORITIES[item['manual_priority']]} · {item['override_author']} · {item['override_at']} · {item['override_reason']}"
        )
    st.subheader("Motivos da avaliação")
    st.table(
        [{"Critério": CRITERIA[r["criterion"]], "Pontos": r["points"], "Motivo": r["reason"]} for r in item["reasons"]]
    )
    st.caption(
        "As contribuições somam a pontuação. Quando faltam evidências mínimas, nenhuma pontuação oficial é atribuída."
    )
    for limitation in item["limitations"]:
        st.warning(limitation)
    with st.expander("Evidências utilizadas"):
        st.write(f"Primeira aparição: {source.get('first_seen')} · Última aparição: {source.get('last_seen')}")
        st.write(
            f"Observações registradas: {source.get('observations')} · Dias distintos observados: {source.get('distinct_observation_days')}"
        )
        st.write("Situação no parceiro: " + source.get("partner_status", "Não informada"))
        st.write(
            f"Início da pendência: {source.get('pending_since')} · Última manifestação humana: {source.get('last_human_at') or 'Não registrada'}"
        )
        st.write("Situação na base: " + source.get("base_status", "Não informada"))
        development = source.get("development")
        if development:
            from services.development_policy import STATES

            st.write(
                f"Desenvolvimento #{development['id']}: {STATES[development['status']]} · Responsável: {development['assigned_to'] or 'Não atribuído'}"
            )
    if source.get("review_item_id"):
        st.link_button("Abrir revisão humana", f"?review={source['review_item_id']}&partner={item['partner']}")
    if source.get("source_url", "").startswith(("https://", "http://")):
        st.link_button("Abrir anúncio", source["source_url"])
    if source.get("development"):
        from ui.development_panel import open_item

        st.button("Abrir desenvolvimento relacionado", on_click=open_item, args=(source["development"]["id"],))
    key = f"priority_form_{case_id}"
    if key not in st.session_state:
        st.session_state[key] = {"revision": item["revision"], "request": str(uuid4())}
    if st.button("Atualizar formulário da prioridade", key=key + "_reload"):
        st.session_state.pop(key, None)
        st.rerun()
    with st.form(key + "_widget"):
        selected = st.selectbox(
            "Alterar prioridade",
            [None, "high", "medium", "low"],
            format_func=lambda v: "Restaurar sugestão automática" if v is None else PRIORITIES[v],
        )
        author = st.text_input("Responsável pela alteração", max_chars=120)
        reason = st.text_area("Justificativa da prioridade", max_chars=4000)
        submitted = st.form_submit_button(
            "Salvar prioridade",
            disabled=service.config.read_only
            or not service.policy["enabled"]
            or not service.policy["allow_manual_override"],
        )
    if submitted:
        try:
            service.override(
                case_id,
                selected,
                author=author,
                reason=reason,
                request_key=st.session_state[key]["request"],
                revision=st.session_state[key]["revision"],
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state.pop(key, None)
            st.rerun()
    with st.expander("Histórico de avaliações e intervenções"):
        page = st.number_input("Página do histórico da avaliação", min_value=1, value=1, step=1)
        history = item if page == 1 else service.detail(case_id, page - 1)
        st.table(
            [
                {
                    "Avaliação": r["id"],
                    "Data": r["calculated_at"],
                    "Pontuação": r["score"],
                    "Sugestão": PRIORITIES[r["suggested_priority"]],
                    "Política": json.loads(r["payload_json"])["policy_hash"][:16],
                }
                for r in history["history"]
            ]
        )
        historical = st.selectbox(
            "Consultar motivos anteriores",
            [None, *[r["id"] for r in history["history"]]],
            format_func=lambda v: f"Avaliação {v}" if v else "Selecione uma avaliação",
        )
        if historical:
            old = json.loads(next(r["payload_json"] for r in history["history"] if r["id"] == historical))
            st.table(
                [
                    {"Critério": CRITERIA[r["criterion"]], "Pontos": r["points"], "Motivo": r["reason"]}
                    for r in old["reasons"]
                ]
            )
        if item["overrides"]:
            st.table(
                [
                    {
                        "Data": r["created_at"],
                        "Responsável": r["author"],
                        "Justificativa": r["reason"],
                        "Antes": PRIORITIES.get(r["before_priority"], "Automática"),
                        "Depois": PRIORITIES.get(r["after_priority"], "Automática"),
                    }
                    for r in item["overrides"]
                ]
            )


def prioritization_page(dashboard):
    service = PrioritizationService(dashboard.config)
    initial = service.listing()
    st.caption(
        "O sistema sugere atenção operacional; o usuário decide. Pontuação alta não confirma necessidade de desenvolvimento."
    )
    if not service.policy["enabled"]:
        st.info("Priorização desabilitada; histórico preservado.")
    if not initial["installed"]:
        st.info("Nenhuma avaliação salva. Use Reavaliar casos para iniciar; navegar não modifica o banco.")
    if initial["stale"]:
        st.warning(
            "Avaliação desatualizada: houve mudança de dados, configuração ou prazo. Reavalie antes de usar as sugestões."
        )
    if st.button("Reavaliar casos", disabled=dashboard.config.read_only or not service.policy["enabled"]):
        try:
            result = service.refresh("dashboard")
            st.session_state.priority_result = (
                f"{result['evaluated']} casos avaliados; {result['changed']} avaliações atualizadas."
            )
            st.rerun()
        except Exception:
            st.error("Não foi possível reavaliar. As decisões humanas foram preservadas; consulte o registro local.")
    if st.session_state.get("priority_result"):
        st.success(st.session_state.priority_result)
    labels = {
        "total": "Casos avaliados",
        "high": "Prioridade alta",
        "medium": "Prioridade média",
        "low": "Prioridade baixa",
        "unassessed": "Informações insuficientes",
        "awaiting_human": "Aguardando decisão humana",
        "manual": "Prioridade manual",
        "development": "Com desenvolvimento",
    }
    cols = st.columns(4)
    for i, (key, label) in enumerate(labels.items()):
        cols[i % 4].metric(label, initial["metrics"].get(key, 0))
    filters = {}
    with st.expander("Filtros de priorização", expanded=True):
        cols = st.columns(3)
        fields = {
            "manufacturer": "Fabricante",
            "model": "Modelo",
            "year": "Ano",
            "partner": "Parceiro da avaliação",
            "base_status": "Situação na base",
            "human_status": "Decisão humana",
            "suggested_priority": "Prioridade sugerida",
            "effective_priority": "Prioridade efetiva",
            "assigned_to": "Responsável",
            "has_development": "Possui desenvolvimento",
        }
        for i, (field, label) in enumerate(fields.items()):
            filters[field] = cols[i % 3].multiselect(
                label,
                initial["facets"][field],
                format_func=lambda v, f=field: (
                    PRIORITIES[v]
                    if f.endswith("priority")
                    else cell("partner", v)
                    if f == "partner"
                    else "Sim"
                    if v is True
                    else "Não"
                    if v is False
                    else str(v)
                    if v
                    else "Sem responsável"
                ),
                placeholder="Todos",
                key="prio_filter_" + field,
            )
        photo = cols[1].selectbox("Fotos da avaliação", ["Todas", "Com foto", "Sem foto"])
        if photo != "Todas":
            filters["photo"] = ["with" if photo == "Com foto" else "without"]
        start = cols[0].date_input("Avaliações a partir de", value=None, format="DD/MM/YYYY")
        end = cols[1].date_input("Avaliações até", value=None, format="DD/MM/YYYY")
        text = st.text_input("Buscar casos", placeholder="Fabricante, modelo, ano, anúncio ou responsável")
    orders = {
        "score_desc": "Maior pontuação",
        "score_asc": "Menor pontuação",
        "pending": "Mais tempo pendente",
        "recent": "Mais recente",
        "model": "Fabricante/modelo",
        "effective": "Prioridade definida pelo usuário",
    }
    sort = st.selectbox("Ordenar avaliações", list(orders), format_func=orders.get)
    result = service.listing(filters, text, sort, start=start, end=end)
    page = st.selectbox("Página da priorização", range(1, max(1, (result["total"] + 7) // 8) + 1))
    if page > 1:
        result = service.listing(filters, text, sort, page - 1, start=start, end=end)
    rows = result["items"]
    st.caption(f"{result['total']} casos · oito por página")
    if rows:
        photos = photo_cells([{**r, "development_item": True} for r in rows], load_image_config())
        st.table(
            [
                {
                    "Foto": photo,
                    "Caso": r["id"],
                    "Moto": f"{r['manufacturer']} {r['model']}",
                    "Ano": r["year"],
                    "Situação na base": r["base_status"],
                    "Prioridade sugerida": PRIORITIES[r["suggested_priority"]],
                    "Prioridade efetiva": PRIORITIES[r["effective_priority"]],
                    "Pontuação": r["score"] if r["score"] is not None else "Não avaliada",
                    "Decisão humana": r["human_status"],
                }
                for r, photo in zip(rows, photos)
            ]
        )
    related = st.session_state.pop("priority_selection", None)
    choices = [None, *[r["id"] for r in rows]]
    if related and related not in choices:
        choices.append(related)
    selected = st.selectbox(
        "Ver motivos da avaliação",
        choices,
        index=choices.index(related) if related else 0,
        format_func=lambda v: f"Caso {v}" if v else "Selecione um caso",
    )
    if selected:
        try:
            priority_detail(service, selected)
        except ValueError as exc:
            st.error(str(exc))
    with st.expander("Simular pesos sem salvar"):
        st.caption(
            "Compara duas configurações sobre os mesmos dados atuais. Não modifica avaliações oficiais, prioridades humanas ou alertas."
        )
        simulated = deepcopy(service.policy)
        cols = st.columns(3)
        for i, (key, label) in enumerate(CRITERIA.items()):
            simulated["weights"][key] = cols[i % 3].number_input(
                label,
                min_value=0.0,
                max_value=100.0,
                value=float(service.policy["weights"][key]),
                key="prio_weight_" + key,
            )
        if st.button("Simular configuração"):
            try:
                simulation = service.simulate(simulated)
                st.success(
                    f"{simulation['changed_band']} de {simulation['evaluated']} avaliações mudariam de faixa. Nenhuma alteração foi salva."
                )
            except ValueError as exc:
                st.error(str(exc))


def development_priority(dashboard, item):
    from database.prioritization_repository import development_assessments

    rows = development_assessments(dashboard.config.database, item["id"], dashboard.config.partner)
    if rows:
        with st.expander("Prioridade operacional sugerida"):
            st.caption(
                "Avaliação independente. A prioridade, o responsável e a etapa do desenvolvimento permanecem como definidos pelo usuário."
            )
            for row in rows:
                st.write(
                    f"Caso {row[0]} · Sugestão: {PRIORITIES[row[2]]} · Pontuação: {row[1] if row[1] is not None else 'Não avaliada'} · Efetiva: {PRIORITIES[row[3] or row[2]]}"
                )
                from ui.alert_panel import navigate

                st.button(
                    "Ver avaliação operacional",
                    key=f"dev_priority_{row[0]}",
                    on_click=navigate,
                    args=("Priorização operacional", "priority_selection", row[0]),
                )
