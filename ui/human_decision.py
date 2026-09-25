"""Direct human confirmation UI; all writes use DashboardService.submit."""

import uuid

import streamlit as st

from ui.textos import ACTIONS, IDENTITY_HELP, validation_message, value

ACTION_LABELS = {
    "CONFIRMAR_MATCH": "Existe na base",
    "NAO_EXISTE_NA_BASE": "Não existe na base",
    "DEIXAR_PENDENTE": "Em dúvida / revisar depois",
    "REJEITAR_CANDIDATO": "Rejeitar candidato",
    "IGNORAR": "Ignorar este caso",
}


def decision_form(service, item, *, compact=False):
    item_id = item["id"]
    if not compact:
        st.subheader("Registrar decisão humana")
    if service.config.read_only:
        st.info("Modo somente leitura. O registro de decisões está desabilitado.")
        return
    draft_key = f"draft_{item_id}"
    receipt_key = f"receipt_{item_id}"
    if receipt_key in st.session_state:
        st.success(st.session_state[receipt_key])
        if st.button("Iniciar outra revisão", key=f"new_{item_id}"):
            st.session_state.pop(receipt_key)
            st.session_state.pop(draft_key, None)
            st.rerun()
        return
    if draft_key not in st.session_state:
        st.session_state[draft_key] = {"request_id": str(uuid.uuid4()), "revision": item["revision"]}
    draft = st.session_state[draft_key]
    if draft["revision"] != item["revision"]:
        st.warning("O item mudou enquanto o formulário estava aberto. Atualize antes de decidir.")
    if st.button("Atualizar item e formulário", key=f"refresh_{item_id}"):
        st.session_state.pop(draft_key, None)
        st.rerun()
    candidates = {m["key"]: m for m in item["selectable_candidates"]}
    suggested = [c["scanner_key"] for c in item["automatic"]["candidates"] if c["scanner_key"] in candidates]
    st.caption("Candidatos sugeridos primeiro. Confirme fabricante, modelo completo/versão, ano e chave.")
    search = st.checkbox("Buscar na base do scanner", key=f"search_scanner_{item_id}")
    if search:
        st.caption(
            "Busca na base vigente, limitada ao fabricante e ano compatíveis com o anúncio. Versões fazem parte do modelo completo do scanner."
        )
        left, right = st.columns(2)
        manufacturer = left.selectbox(
            "Fabricante na base",
            sorted({m["manufacturer"] for m in candidates.values()}),
            index=None,
            placeholder="Todos os fabricantes compatíveis",
            key=f"search_brand_{item_id}",
        )
        year = right.selectbox(
            "Ano na base",
            sorted({m["year"] for m in candidates.values()}),
            index=None,
            placeholder="Todos os anos compatíveis",
            key=f"search_year_{item_id}",
        )
        text = st.text_input(
            "Modelo ou texto livre na base", key=f"search_text_{item_id}", placeholder="Nome, versão ou chave da base"
        )
        found = service.search_scanner_candidates(item_id, text, manufacturer, year)
        candidates = {m["key"]: m for m in found}
        st.caption(f"{len(found)} registros compatíveis encontrados. Nenhum é selecionado automaticamente.")
        if not found:
            st.info("Nenhum registro compatível. Ajuste a busca; não é possível confirmar sem um vínculo.")
    else:
        # Retain all current compatible records in the legacy selector; suggestions lead.
        candidates = {k: candidates[k] for k in dict.fromkeys([*suggested, *candidates])}
    selected_key = f"candidate_{item_id}"
    if st.session_state.get(selected_key) not in candidates:
        st.session_state.pop(selected_key, None)
    (st.caption if compact else st.warning)(IDENTITY_HELP)
    with st.form(f"decision_{item_id}", clear_on_submit=False):
        action = st.selectbox(
            "Ação", list(ACTIONS), format_func=lambda label: ACTION_LABELS[ACTIONS[label]], key=f"action_{item_id}"
        )
        candidate = st.selectbox(
            "Candidato (obrigatório para confirmar ou rejeitar)",
            list(candidates),
            index=None,
            placeholder="Escolha explicitamente um candidato",
            format_func=lambda k: (
                f"{candidates[k]['manufacturer']} · {candidates[k]['model']} · {candidates[k]['year']} · {k} · {value(candidates[k]['status'])}"
            ),
            key=f"candidate_{item_id}",
        )
        reviewer = st.text_input("Revisor", key=f"reviewer_{item_id}")
        note = st.text_area("Justificativa", key=f"note_{item_id}")
        submitted = st.form_submit_button("Salvar decisão", type="primary")
    if submitted:
        try:
            service.submit(
                item_id,
                ACTIONS[action],
                reviewer,
                note,
                candidate if ACTIONS[action] in {"CONFIRMAR_MATCH", "REJEITAR_CANDIDATO"} else None,
                draft["request_id"],
                draft["revision"],
            )
        except ValueError as exc:
            st.error(validation_message(exc))
        except Exception:
            st.error(
                "Não foi possível confirmar o salvamento. Atualize e confira o histórico antes de tentar novamente."
            )
        else:
            st.session_state[receipt_key] = (
                "Decisão registrada. Identidade confirmada como ausente da versão atual da base."
                if ACTIONS[action] == "NAO_EXISTE_NA_BASE"
                else "Decisão registrada. Resultado efetivo atualizado e auditoria preservada."
            )
            st.rerun()
