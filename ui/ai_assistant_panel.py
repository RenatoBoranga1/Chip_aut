"""Session-only chat; navigation is a user click, never a generated tool call."""

import streamlit as st

from services.ai_assistant_service import AIAssistantService
from services.ai_context_service import new_conversation
from services.ai_guardrails import NOT_CONFIGURED
from ui.navigation import request_navigation

SUGGESTIONS = (
    "Resumo de hoje",
    "Quais motos novas apareceram esta semana?",
    "Quais motos aguardam decisão humana?",
    "Quais motos estão em desenvolvimento?",
    "Quais são os principais alertas?",
    "Quais sistemas existem para uma moto?",
    "Qual cabo é usado em determinada aplicação?",
    "Resuma os últimos 30 dias.",
)
SOURCE_LABELS = {
    "scanner_vehicle": "Veículo na base do scanner",
    "scanner_application": "Aplicação do scanner",
    "scanner_base_version": "Versão da base do scanner",
    "review_item": "Fila de revisão",
    "partner_registry": "Cadastro e avaliação de parceiros",
    "development_item": "Desenvolvimento",
    "priority_case": "Priorização operacional",
    "management_metrics": "Indicadores gerenciais",
    "alert": "Alertas",
    "partner_advertisement": "Anúncio do parceiro",
    "assistant_policy": "Política do assistente",
}


def render_answer(answer):
    st.text(answer["text"])
    if answer.get("period"):
        p = answer["period"]
        st.caption(f"Período: {p['start']} a {p['end']} · {p['timezone']}")
    for fact in answer["facts"]:
        # Plain text prevents source-controlled HTML/Markdown links or tracking images.
        st.text(fact["text"])
    if answer.get("total"):
        st.caption(
            f"Mostrando {answer.get('displayed', len(answer['facts']))} de {answer['total']} {answer.get('count_label', 'registros')}."
        )
    if answer["sources"]:
        with st.expander("Fontes consultadas"):
            for source in answer["sources"]:
                st.text(
                    f"{SOURCE_LABELS.get(source['type'], source['type'])} · referência {source['id']}"
                    + (f" · base {source['base_id']}" if source.get("base_id") is not None else "")
                )
    if answer.get("audit_warning"):
        st.warning(answer["audit_warning"])


def assistant_page(dashboard):
    try:
        service = AIAssistantService(dashboard.config.database, dashboard.config.partner)
    except (ValueError, OSError, TypeError):
        st.info(NOT_CONFIGURED)
        return
    st.caption("Somente leitura. As respostas usam dados do sistema e não substituem decisões humanas.")
    scope = (str(dashboard.config.database.resolve()), dashboard.config.partner)
    state = st.session_state.setdefault("ai_conversation", new_conversation())
    if state.get("scope") not in (None, scope):
        state = st.session_state["ai_conversation"] = new_conversation()
    if st.button("Nova conversa", key="ai_new"):
        st.session_state["ai_conversation"] = new_conversation()
        st.rerun()
    if not service.configured:
        st.info(NOT_CONFIGURED)
        return
    info = service.model_info()
    st.caption(
        "Modo de demonstração offline (FakeLLMProvider)."
        if info["provider"] == "fake"
        else f"Provider: {info['provider']} · modelo: {info['model']}"
    )
    question = None
    with st.expander("Perguntas sugeridas", expanded=not state["messages"]):
        for index, text in enumerate(SUGGESTIONS):
            if st.button(text, key=f"ai_suggestion_{index}"):
                question = text
    if state["selected_vehicle_id"]:
        st.caption(f"Veículo selecionado: #{state['selected_vehicle_id']} · base {state['selected_base_id']}")
    for message in state["messages"]:
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.text(message["text"])
            else:
                render_answer(message["answer"])
    latest = next((m["answer"] for m in reversed(state["messages"]) if m["role"] == "assistant"), None)
    if latest and latest["choices"]:
        choices = {r["id"]: r for r in latest["choices"]}
        chosen = st.selectbox(
            "Selecione um veículo",
            [None, *choices],
            key="ai_choice",
            format_func=lambda key: (
                "Selecione..."
                if key is None
                else f"#{key} · {choices[key]['manufacturer']} {choices[key]['model']} {choices[key]['year']}"
            ),
        )
        if st.button("Consultar veículo selecionado", key="ai_select") and chosen in choices:
            question = f"Mostre o veículo #{chosen}"
    if latest and latest["route"]:
        if st.button("Abrir " + latest["route"], key="ai_open_source"):
            request_navigation(latest["route"])
            st.rerun()
    typed = st.chat_input("Pergunte sobre os dados do sistema", max_chars=2000, key="ai_question")
    question = typed or question
    if question:
        with st.spinner("Consultando dados e organizando evidências..."):
            service.ask(question, state)
        st.rerun()
