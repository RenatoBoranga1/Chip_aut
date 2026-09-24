"""Portuguese development UI; all commands and policies live in services."""

import logging
from datetime import datetime
from uuid import uuid4

import streamlit as st

from services.development_policy import PRIORITIES, REASONS, STATES, TECHNICAL, TRANSITIONS
from services.development_service import DevelopmentService, allowed_reasons
from services.vehicle_image_config import load_image_config
from ui.textos import ALERT_STATES, cell, value
from ui.vehicle_images import photo_cells, vehicle_photo


def open_item(item_id):
    st.session_state.navigation = "Motos para desenvolvimento"
    st.session_state.development_selection = item_id


def display_date(raw):
    if not raw:
        return "Não informada"
    try:
        return datetime.fromisoformat(raw).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return raw


def request_key(key):
    name = "dev_request_" + key
    if name not in st.session_state:
        st.session_state[name] = str(uuid4())
    return st.session_state[name]


def report_error(exc):
    if isinstance(exc, ValueError):
        st.error(str(exc))
    else:
        logging.getLogger(__name__).exception("development_command_failed")
        st.error("Não foi possível salvar. Atualize o item e tente novamente; o histórico foi preservado.")


def offer_creation(dashboard, kind, identifier, key):
    try:
        service = DevelopmentService(dashboard.config)
        if not service.policy["enabled"]:
            return
        source = service.source(kind, identifier)
        existing = service.existing(kind, identifier)
    except (ValueError, OSError):
        return
    if existing:
        st.info(f"Já está em desenvolvimento · item {existing}")
        st.button("Abrir item de desenvolvimento", key="dev_open_" + key, on_click=open_item, args=(existing,))
    with st.expander(
        "Adicionar às motos para desenvolvimento" if not existing else "Registrar esta origem no item existente"
    ):
        st.caption(
            "A inclusão confirma uma necessidade de acompanhamento. Não confirma identidade, ausência ou suporte e não altera a base do scanner."
        )
        with st.form("dev_create_" + key):
            actor = st.text_input("Seu nome", key="dev_actor_" + key, max_chars=120)
            reason = st.selectbox(
                "Motivo da inclusão", allowed_reasons(source), format_func=REASONS.get, key="dev_reason_" + key
            )
            priority = st.selectbox(
                "Prioridade do desenvolvimento",
                list(PRIORITIES),
                format_func=PRIORITIES.get,
                key="dev_priority_" + key,
                index=list(PRIORITIES).index(source.get("priority") or "medium"),
            )
            note = st.text_area("Justificativa da inclusão", key="dev_note_" + key, max_chars=4000)
            confirmed = st.checkbox(
                "Confirmo a inclusão desta necessidade para acompanhamento", key="dev_confirm_" + key
            )
            submitted = st.form_submit_button(
                "Confirmar inclusão" if not existing else "Registrar origem", disabled=dashboard.config.read_only
            )
        if submitted:
            try:
                item_id = service.create(
                    kind,
                    identifier,
                    actor=actor,
                    justification=note,
                    reason=reason,
                    priority=priority,
                    confirmed=confirmed,
                    command_key=request_key(key),
                )
            except Exception as exc:
                report_error(exc)
            else:
                st.success(f"Item {item_id} registrado. O resultado da revisão permanece preservado.")
                st.session_state.pop("dev_request_" + key, None)
                st.button("Ver item registrado", key="dev_created_" + key, on_click=open_item, args=(item_id,))


def origin_picker(dashboard, rows, key, scanner=False):
    if not rows:
        return
    options = {str(r["scanner_key"] if scanner else r["external_id"]): r for r in rows}
    selected = st.selectbox(
        "Selecionar moto para desenvolvimento",
        [None, *options],
        format_func=lambda n: (
            "Selecione uma moto"
            if n is None
            else f"{options[n].get('manufacturer')} · {options[n].get('model')} · {options[n].get('year')} · {n}"
        ),
        key="dev_source_" + key,
    )
    if selected is not None:
        offer_creation(dashboard, "scanner" if scanner else "advertisement", selected, key + "_" + selected)


def development_page(dashboard):
    try:
        service = DevelopmentService(dashboard.config)
        initial = service.listing()
    except Exception as exc:
        report_error(exc)
        return
    if not service.policy["enabled"]:
        st.info("Gestão de desenvolvimento desabilitada. O histórico persistido permanece preservado.")
        return
    st.caption(
        "Necessidades incluídas explicitamente. Concluir um item não altera a cobertura da base do scanner. Datas em UTC."
    )
    if not initial["installed"]:
        st.info("Nenhum item de desenvolvimento registrado. A primeira inclusão autorizada inicializa esta gestão.")
    indicators = [("active", "Total ativo"), *STATES.items(), ("high", "Alta prioridade")]
    for start in range(0, len(indicators), 4):
        cols = st.columns(4)
        for col, (name, label) in zip(cols, indicators[start : start + 4]):
            col.metric(label, initial["metrics"].get(name, 0))
    with st.expander("Filtros de desenvolvimento", expanded=True):
        filters = {}
        cols = st.columns(3)
        mappings = [
            ("status", "Situação", STATES),
            ("priority", "Prioridade", PRIORITIES),
            ("reason", "Motivo", REASONS),
        ]
        for col, (field, label, mapping) in zip(cols, mappings):
            filters[field] = col.multiselect(
                label, list(mapping), format_func=mapping.get, key="dev_filter_" + field, placeholder="Todos"
            )
        for i, (field, label) in enumerate(
            [("assigned_to", "Responsável"), ("manufacturer", "Fabricante"), ("year", "Ano"), ("partner", "Parceiro")]
        ):
            filters[field] = cols[i % 3].multiselect(
                label,
                initial["facets"].get(field, []),
                key="dev_filter_" + field,
                placeholder="Todos",
                format_func=lambda v, field=field: (
                    cell("partner", v) if field == "partner" else str(v) if v else "Sem responsável"
                ),
            )
        photo = cols[1].selectbox("Fotos", ["Todas", "Com foto", "Sem foto"], key="dev_photos")
        if photo != "Todas":
            filters["photo"] = ["with" if photo == "Com foto" else "without"]
        text = st.text_input("Buscar desenvolvimento", placeholder="Fabricante, modelo, ano ou responsável")
        sorts = {
            "priority": "Prioridade",
            "recent": "Mais recente",
            "oldest": "Mais antigo",
            "model": "Fabricante/modelo",
            "status": "Situação",
        }
        sort = st.selectbox("Ordenar desenvolvimento por", list(sorts), format_func=sorts.get)
    filtered = service.listing(filters=filters, text=text, sort=sort)
    page = st.selectbox("Página de desenvolvimento", range(1, max(1, (filtered["total"] + 7) // 8) + 1))
    result = filtered if page == 1 else service.listing(filters=filters, text=text, sort=sort, page=page - 1)
    rows = result["items"]
    st.caption(f"{result['total']} itens · oito por página")
    if rows:
        config = load_image_config()
        photos = photo_cells([{**r, "development_item": True} for r in rows], config)
        st.markdown(
            "<style>[data-testid='stTable'] img {min-width:100px;max-width:160px}</style>", unsafe_allow_html=True
        )
        st.table(
            [
                {
                    "Foto": p,
                    "Item": r["id"],
                    "Fabricante": r["manufacturer"],
                    "Modelo": r["model"],
                    "Ano": r["year"],
                    "Situação": STATES[r["status"]],
                    "Prioridade": PRIORITIES[r["priority"]],
                    "Responsável": r["assigned_to"] or "Sem responsável",
                    "Motivo": REASONS[r["reason"]],
                    "Parceiros": ", ".join(cell("partner", p) for p in (r["partners"] or "").split(",")),
                    "Primeira aparição": display_date(r["first_seen_at"]),
                    "Última atualização": display_date(r["updated_at"]),
                    "Dias na situação": r["days_in_status"],
                    "Acompanhamento": "Atenção ao prazo" if r["attention"] else "—",
                }
                for r, p in zip(rows, photos)
            ]
        )
    else:
        st.info("Nenhum item para esta seleção.")
    options = [None, *[r["id"] for r in rows]]
    requested = st.session_state.get("development_selection")
    if requested and requested not in options:
        options.append(requested)
    selected = st.selectbox(
        "Abrir item de desenvolvimento",
        options,
        format_func=lambda n: f"Item {n}" if n else "Selecione um item",
        key="development_selection",
    )
    if selected:
        development_detail(dashboard, service, selected)
    with st.expander("Inclusão a partir de busca manual"):
        text = st.text_input("Buscar moto na base ou no estoque", key="dev_manual_search")
        if len(text.strip()) >= 2:
            found = dashboard.search(text)
            origin_picker(dashboard, found["Anúncios"][:50], "manual_ads")
            origin_picker(dashboard, found["Scanner"][:50], "manual_scanner", scanner=True)
            st.caption("Até 50 resultados por origem. Refine a busca se necessário.")


def development_detail(dashboard, service, item_id):
    try:
        item = service.detail(item_id)
    except Exception as exc:
        report_error(exc)
        return
    st.subheader(f"Item {item_id} · {item['manufacturer']} {item['model']} · {item['year']}")
    st.subheader("Resumo")
    st.write(
        f"{STATES[item['status']]} · prioridade {PRIORITIES[item['priority']]} · responsável: {item['assigned_to'] or 'Não atribuído'}"
    )
    st.write("Motivo registrado na inclusão: " + REASONS[item["reason"]])
    st.caption(
        f"Incluído por {item['created_by']} em {item['created_at']} · {item['days_in_status']} dias nesta situação"
    )
    if item["attention"]:
        st.warning(
            "Confira o andamento: o prazo de acompanhamento nesta situação foi ultrapassado. Não representa falha técnica."
        )
    st.subheader("Origem")
    pages = max(1, (max(item["history_count"], item["origin_count"]) + 29) // 30)
    history_page = st.selectbox("Página de origens e histórico", range(1, pages + 1), key=f"dev_history_{item_id}")
    if history_page > 1:
        item = service.detail(item_id, history_page - 1)
    ad = item["source"]["advertisement"]
    photo_ad = {**ad, **dashboard.image_metadata(ad)}
    vehicle_photo(photo_ad, {"development_item": True}, detail=True)
    st.write(
        f"Preço: {ad.get('price') or 'Não informado'} · Quilometragem: {ad.get('mileage') if ad.get('mileage') is not None else 'Não informada'} · Versão: {ad.get('version') or 'Não estruturada'}"
    )
    for origin in item["origins"]:
        observed = origin["payload"]["advertisement"]
        st.write(
            f"{cell('partner', origin['partner'])} · anúncio {origin['external_id']} · {origin['occurrence_count']} observação(ões) · primeira {origin['first_seen_at']} · última {origin['last_seen_at']}"
        )
        if observed.get("source_url", "").startswith(("https://", "http://")):
            st.link_button("Abrir anúncio", observed["source_url"])
        st.caption(
            f"Preço observado: {observed.get('price') or 'Não informado'} · Quilometragem observada: {observed.get('mileage') if observed.get('mileage') is not None else 'Não informada'}"
        )
        if origin["review_item_id"] and origin["partner"] == dashboard.config.partner:
            from ui.alert_panel import navigate

            st.button(
                "Abrir revisão relacionada",
                key=f"dev_review_{origin['id']}",
                on_click=navigate,
                args=("Fila de revisão", "related_review_id", origin["review_item_id"]),
            )
        if origin["alert_id"]:
            st.caption(f"Alerta de origem #{origin['alert_id']}")
    st.subheader("Scanner e cobertura")
    if item["may_be_addressed"]:
        st.warning(
            "Pode ter sido atendido pela nova base. Confira os sistemas e valide o resultado; o item não foi concluído automaticamente."
        )
    target = item["current_scanner"]
    st.caption(f"Base na inclusão: {item['base_version']} · base atual: {item['current_base']}")
    if target:
        st.write(f"{target['manufacturer']} {target['model']} · {target['year']} · {value(target['status'])}")
        for field, label in [
            ("supported_systems", "Sistemas suportados"),
            ("unsupported_systems", "Sistemas sem suporte"),
            ("analysis_systems", "Sistemas em análise"),
            ("unknown_systems", "Sistemas sem status"),
        ]:
            st.write(label + ": " + (", ".join(target[field]) or "Nenhum registro"))
    else:
        st.info(
            "Ausência confirmada na versão atual da base"
            if item["absence_confirmed_current"]
            else "Possível ausência — ainda precisa de confirmação"
        )
        candidate = item["reconciliation_candidate"]
        if candidate:
            st.write(
                f"Entrada candidata na nova base: {candidate['manufacturer']} {candidate['model']} · {candidate['year']}"
            )
            st.caption(
                "Confira esta entrada na base do scanner e revise a identidade. Nenhum suporte foi atribuído automaticamente ao item."
            )
    if item["completed_at"]:
        st.caption(
            f"Concluído em {item['completed_at']} · versão informada: {item['completion_version'] or 'Não informada'}"
        )
    st.subheader("Fluxo de desenvolvimento")
    draft_key = f"dev_revision_{item_id}"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = item["revision"]
    if st.session_state[draft_key] != item["revision"]:
        st.warning("Este item mudou desde a abertura do formulário. Atualize antes de salvar.")
    if st.button("Atualizar item e formulário", key=f"dev_refresh_{item_id}"):
        st.session_state.pop(draft_key, None)
        st.session_state.pop(f"dev_request_edit_{item_id}", None)
        st.rerun()
    actions = {
        "status": "Alterar situação / concluir / descartar / reabrir",
        "priority": "Alterar prioridade",
        "assigned_to": "Atribuir responsável",
        "note": "Adicionar observação",
        "checklist": "Atualizar checklist",
        "technical": "Registrar informações técnicas",
    }
    action = st.selectbox("Ação no item", list(actions), format_func=actions.get, key=f"dev_action_{item_id}")
    with st.form(f"dev_edit_{item_id}_{action}"):
        actor = st.text_input("Autor da alteração", max_chars=120)
        note = st.text_area("Justificativa da alteração", max_chars=4000)
        completion_version = None
        if action == "status":
            new = st.selectbox(
                "Nova situação", [s for s in STATES if s in TRANSITIONS[item["status"]]], format_func=STATES.get
            )
            completion_version = st.text_input("Versão da base/scanner na conclusão (opcional)", max_chars=120)
        elif action == "priority":
            new = st.selectbox(
                "Nova prioridade",
                list(PRIORITIES),
                format_func=PRIORITIES.get,
                index=list(PRIORITIES).index(item["priority"]),
            )
        elif action == "assigned_to":
            new = (
                st.selectbox(
                    "Responsável", ["", *service.policy["assignees"]], format_func=lambda v: v or "Não atribuído"
                )
                if service.policy["assignees"]
                else st.text_input("Responsável", value=item["assigned_to"], max_chars=120)
            )
        elif action == "note":
            new = st.text_area("Observação", max_chars=8000)
        elif action == "checklist":
            new = {
                k: st.checkbox(v["label"], value=v["done"], key=f"dev_check_{item_id}_{k}")
                for k, v in item["checklist"].items()
            }
        else:
            new = {
                k: st.text_input(
                    label, value=item["technical"].get(k, ""), key=f"dev_tech_{item_id}_{k}", max_chars=4000
                )
                for k, label in TECHNICAL.items()
            }
        submitted = st.form_submit_button("Registrar alteração", disabled=dashboard.config.read_only)
    if submitted:
        try:
            service.change(
                item_id,
                action,
                new,
                actor=actor,
                justification=note,
                command_key=request_key(f"edit_{item_id}"),
                expected_revision=st.session_state[draft_key],
                completion_version=completion_version,
            )
        except Exception as exc:
            report_error(exc)
        else:
            st.session_state.pop(f"dev_request_edit_{item_id}", None)
            st.session_state.pop(draft_key, None)
            st.rerun()
    st.subheader("Checklist")
    for entry in item["checklist"].values():
        st.write(("✓ " if entry["done"] else "○ ") + entry["label"])
    with st.expander("Informações técnicas"):
        for field, label in TECHNICAL.items():
            st.write(label + ": " + (item["technical"].get(field) or "Não informado"))
    st.subheader("Observações")
    notes = [e for e in item["history"] if e["action"] == "note"]
    if not notes:
        st.caption("Nenhuma observação nesta página do histórico.")
    for event in notes:
        st.write(f"{event['actor']} · {event['created_at']}")
        st.text(event["after"]["text"])
    st.subheader("Histórico")
    labels = {"CREATE": "Criação", "ORIGIN": "Origem registrada", **actions}
    for event in item["history"]:
        st.write(f"{event['created_at']} · {event['actor']} · {labels.get(event['action'], 'Alteração')}")
        if event["action"] == "status":
            st.write(f"{STATES[event['before']['status']]} → {STATES[event['after']['status']]}")
        elif event["action"] == "priority":
            st.write(f"{PRIORITIES[event['before']['priority']]} → {PRIORITIES[event['after']['priority']]}")
        elif event["action"] == "assigned_to":
            st.write(
                f"{event['before']['assigned_to'] or 'Não atribuído'} → {event['after']['assigned_to'] or 'Não atribuído'}"
            )
        elif event["action"] == "technical":
            for field, observed in event["after"].items():
                if event["before"].get(field) != observed:
                    st.text(
                        f"{TECHNICAL[field]}: {event['before'].get(field) or 'Não informado'} → {observed or 'Não informado'}"
                    )
        elif event["action"] == "checklist":
            for field, observed in event["after"].items():
                previous = event["before"].get(field, {"done": False})
                if previous["done"] != observed["done"]:
                    st.text(f"{observed['label']}: {'Marcado' if observed['done'] else 'Desmarcado'}")
        st.text(event["justification"])
    st.subheader("Alertas relacionados")
    if item["alerts"]:
        st.table([{"Alerta": r["title"], "Situação": ALERT_STATES[r["status"]]} for r in item["alerts"]])
    else:
        st.caption("Nenhum aviso de desenvolvimento nesta página.")
