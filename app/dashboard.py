"""Streamlit presentation only; all operational rules live in services/repositories."""

import logging
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.dashboard_service import DashboardConfig, DashboardService, filter_rows  # noqa: E402

PAGES = [
    "Visão geral",
    "Fila de Revisão",
    "Estoque WR Motos",
    "Sem suporte",
    "Suporte parcial",
    "Possíveis novas motos",
    "Base do Scanner",
    "Busca global",
    "Histórico",
]
LABELS = {
    "id": "Revisão",
    "manufacturer": "Fabricante",
    "model": "Modelo",
    "version": "Versão",
    "year": "Ano",
    "partner": "Parceiro",
    "priority": "Prioridade",
    "state": "Estado da revisão",
    "automatic_type": "Matching automático",
    "effective_type": "Identidade efetiva",
    "score": "Score",
    "coverage": "Cobertura",
    "last_seen": "Última aparição",
    "external_id": "ID do anúncio",
    "source_url": "Anúncio",
    "scanner_key": "Chave do scanner",
    "price": "Preço (R$)",
    "mileage": "KM",
    "supported_systems": "Sistemas suportados",
    "unsupported_systems": "Sistemas sem suporte",
    "analysis_systems": "Sistemas em análise",
    "unknown_systems": "Sistemas sem status",
    "evidence": "Evidência",
    "status": "Status",
    "system_count": "Sistemas",
    "latest_date": "Data relevante",
}
ACTIONS = {
    "Confirmar match": "CONFIRMAR_MATCH",
    "Rejeitar candidato": "REJEITAR_CANDIDATO",
    "Confirmar ausência na base atual": "NAO_EXISTE_NA_BASE",
    "Adiar": "DEIXAR_PENDENTE",
    "Ignorar": "IGNORAR",
}


def table(rows, key, columns=None):
    if not rows:
        st.info("Nenhum registro para esta seleção.")
        return
    size = 50
    pages = (len(rows) + size - 1) // size
    page = st.selectbox("Página", range(1, pages + 1), key=f"{key}_page") if pages > 1 else 1
    st.caption(f"{len(rows)} registros · página {page} de {pages}")
    data = [
        {LABELS.get(k, k): v for k, v in row.items() if columns is None or k in columns}
        for row in rows[(page - 1) * size : page * size]
    ]
    st.dataframe(
        data,
        hide_index=True,
        width="stretch",
        column_config={"Anúncio": st.column_config.LinkColumn("Anúncio", display_text="Abrir anúncio")},
    )


def filtered(rows, key):
    fields = ["priority", "state", "manufacturer", "year", "automatic_type", "coverage", "partner"]
    filters = {}
    with st.expander("Filtros", expanded=True):
        cols = st.columns(4)
        for n, field in enumerate(fields):
            options = sorted({r.get(field) for r in rows if r.get(field) is not None}, key=str)
            filters[field] = cols[n % 4].multiselect(LABELS[field], options, key=f"{key}_{field}")
        text = st.text_input("Texto livre", key=f"{key}_text", placeholder="Modelo, ano, ID ou chave do scanner")
        sort = st.selectbox(
            "Ordenação",
            ["priority", "recent", "oldest", "model"],
            format_func=lambda v: {
                "priority": "Prioridade",
                "recent": "Mais recente",
                "oldest": "Mais antigo",
                "model": "Fabricante / modelo",
            }[v],
            key=f"{key}_sort",
        )
    return filter_rows(rows, filters, text, sort)


def systems(moto):
    if not moto:
        st.info("Identidade ainda sem vínculo válido com a base. Suporte não confirmado.")
        return
    st.write(f"**Cobertura atual: {moto['status']}**")
    for field in ("supported_systems", "unsupported_systems", "analysis_systems", "unknown_systems"):
        st.write(f"**{LABELS[field]}:** {', '.join(moto[field]) or 'Nenhum registro'}")


def detail(service, item_id):
    item = service.detail(item_id)
    ad, auto, effective = item["advertisement"], item["automatic"], item["effective"]
    st.subheader(f"Revisão #{item_id} · {ad['manufacturer']} {ad['model']}")
    st.caption(
        f"{item['state']} · prioridade {item['priority']} · base {item['base_id']} · coleta {item['collection_id']}"
    )
    if item["stale_reason"] or item["state"] == "invalidated":
        st.warning("Decisão ou resultado desatualizado. O caso precisa de nova revisão na base atual.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Ano", ad["year"] or "—")
    c2.metric("Preço (R$)", ad.get("price") or "—")
    c3.metric("Quilometragem", ad.get("mileage") if ad.get("mileage") is not None else "—")
    st.write(f"Versão: {ad.get('version') or 'Não estruturada no anúncio'} · ID: {ad['external_id']}")
    st.caption(f"Primeira aparição: {item['first_seen']} · última: {item['last_seen']}")
    if ad.get("source_url", "").startswith(("https://", "http://")):
        st.link_button("Abrir anúncio em nova aba", ad["source_url"])
    with st.expander("Texto original do anúncio"):
        st.text(ad["raw_name"])
        st.text(ad["raw_text"])
    st.subheader("Matching automático preservado")
    st.write(f"**{auto['match_type']}** · score: {auto['confidence']}")
    for reason in auto["reasons"]:
        st.write(reason)
    table(auto["candidates"], f"candidates_{item_id}")
    st.subheader("Identidade efetiva e cobertura")
    st.write(f"**{effective['match_type']}** · {effective['scanner_key'] or 'Sem chave vinculada'}")
    if effective["match_type"] == "CONFIRMADO_AUSENTE_NA_BASE":
        st.info("Identidade confirmada como ausente da versão atual da base.")
    systems(item["systems"])
    with st.expander("Memória e auditoria"):
        decision = item["human_decision"]
        if decision:
            st.write(
                f"Decisão #{decision['id']} · origem: item {decision['review_item_id']}, execução {decision['run_id']}, base {decision['import_id']}"
            )
            st.write(f"Aplicação atual: {item['state']} · validade: {item['stale_reason'] or 'Válida'}")
            st.json(
                {"policy": decision["policy_json"], "normalized_identity": decision["identity_json"]}, expanded=False
            )
        else:
            st.write("Nenhuma decisão humana aplicável.")
        table(
            [
                {
                    k: v
                    for k, v in d.items()
                    if k not in {"policy_json", "identity_json", "signature", "target_identity_json"}
                }
                for d in item["history"]
            ],
            f"decisions_{item_id}",
        )
        st.write("Eventos de invalidação", item["events"])
    st.subheader("Registrar decisão humana")
    if service.config.read_only:
        st.info("Modo somente leitura. Ações desabilitadas por MOTO_READ_ONLY.")
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
    st.warning("Confirmar identidade não altera o status de suporte.")
    with st.form(f"decision_{item_id}", clear_on_submit=False):
        action = st.selectbox("Ação", list(ACTIONS), key=f"action_{item_id}")
        candidate = st.selectbox(
            "Candidato (obrigatório para confirmar ou rejeitar)",
            list(candidates),
            index=None,
            placeholder="Escolha explicitamente um candidato",
            format_func=lambda k: f"{k} · {candidates[k]['status']}",
            key=f"candidate_{item_id}",
        )
        reviewer = st.text_input("Reviewer", key=f"reviewer_{item_id}")
        note = st.text_area("Justificativa", key=f"note_{item_id}")
        submitted = st.form_submit_button("Salvar decisão", type="primary")
    if submitted:
        try:
            service.submit(
                item_id,
                ACTIONS[action],
                reviewer,
                note,
                candidate if action in {"Confirmar match", "Rejeitar candidato"} else None,
                draft["request_id"],
                draft["revision"],
            )
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error(
                "Não foi possível confirmar o salvamento. Atualize e confira o histórico antes de tentar novamente."
            )
        else:
            st.session_state[receipt_key] = (
                "Decisão registrada. Identidade confirmada como ausente da versão atual da base."
                if action == "Confirmar ausência na base atual"
                else "Decisão registrada. Resultado efetivo atualizado e auditoria preservada."
            )
            st.rerun()


def main():
    st.set_page_config(page_title="Moto Coverage · Operação", page_icon="🏍", layout="wide")
    config = DashboardConfig.from_env()
    service = DashboardService(config)
    st.sidebar.title("Moto Coverage")
    st.sidebar.caption("OPERAÇÃO · WR MOTOS")
    try:
        snapshot = service.snapshot()
        partners = snapshot["partners"] or [config.partner]
        partner = st.sidebar.selectbox(
            "Parceiro", partners, index=partners.index(config.partner) if config.partner in partners else 0
        )
        if partner != config.partner:
            service = DashboardService(replace(config, partner=partner))
            snapshot = service.snapshot()
    except Exception:
        logging.getLogger(__name__).exception("dashboard_read_failed")
        st.error(
            "Não foi possível abrir a base operacional. Verifique MOTO_DB, o arquivo SQLite e as migrations pela CLI."
        )
        st.stop()
    page = st.sidebar.radio("Navegação", PAGES, key="navigation")
    st.sidebar.caption(
        f"Base {snapshot['base_id']} · {'Somente leitura' if config.read_only else 'Revisões habilitadas'}"
    )
    st.sidebar.button("Atualizar dados")
    st.title(page)
    st.caption("Identidade, decisões humanas e cobertura do scanner — com histórico preservado.")
    if snapshot["zero_km_warning"]:
        st.warning("Classificação 0 km indisponível devido inconsistência observada no site")
    if page == "Visão geral":
        cols = st.columns(4)
        cols[0].metric("Anúncios ativos", len(snapshot["stock"]))
        cols[1].metric("Fila pendente", sum(snapshot["states"].get(s, 0) for s in ("pending", "invalidated")))
        cols[2].metric("Prioridade alta", snapshot["priorities"].get("high", 0))
        cols[3].metric("Base do scanner", snapshot["base_id"])
        left, right = st.columns(2)
        with left:
            st.subheader("Matching automático registrado")
            table([{"Classificação": k, "Anúncios": v} for k, v in snapshot["matching"].items()], "metrics_matching")
            st.subheader("Fila de revisão")
            table(
                [
                    {"Estado": k, "Itens": snapshot["states"].get(k, 0)}
                    for k in ("pending", "invalidated", "resolved", "deferred", "ignored", "reused")
                ],
                "metrics_queue",
            )
            st.caption(
                "Prioridades pendentes: "
                + " · ".join(
                    f"{label}: {snapshot['priorities'].get(key, 0)}"
                    for key, label in [("high", "Alta"), ("medium", "Média"), ("low", "Baixa")]
                )
            )
        with right:
            st.subheader("Cobertura efetiva")
            kinds = list(
                dict.fromkeys(
                    [
                        "SUPORTADO",
                        "SEM_SUPORTE",
                        "SUPORTE_PARCIAL",
                        "EM_ANALISE",
                        "SEM_STATUS",
                        "CONFIRMADO_AUSENTE_NA_BASE",
                        *snapshot["coverage"],
                    ]
                )
            )
            table([{"Cobertura": k, "Anúncios": snapshot["coverage"].get(k, 0)} for k in kinds], "metrics_coverage")
            st.info("Não encontrada na base não significa SEM_SUPORTE. Cobertura depende de identidade válida.")
        st.subheader("Última coleta")
        latest = snapshot["latest"]
        if latest:
            summary = latest["summary"]
            st.write(f"{snapshot['partner']} · {latest['created_at']} · {latest['status']} · coleta {latest['id']}")
            st.write(
                {
                    "Páginas": len(summary.get("pages", [])),
                    "Total bruto": summary.get("metadata", {}).get("observed_cards"),
                    "Duplicados": summary.get("metadata", {}).get("duplicate_occurrences"),
                    "Total líquido": latest["count"],
                    "Falhas": len(summary.get("errors", [])),
                    "Avisos de parsing": sum(latest["warnings"].values()),
                    **latest["delta"],
                }
            )
            with st.expander("Falhas, avisos e evidências da coleta"):
                st.json(
                    {
                        "errors": summary.get("errors", []),
                        "warnings": latest["warnings"],
                        "metadata": summary.get("metadata", {}),
                    }
                )
        else:
            st.info("Nenhuma coleta disponível.")
    elif page == "Fila de Revisão":
        rows = filtered(snapshot["queue"], "queue")
        table(
            rows,
            "queue",
            [
                "id",
                "priority",
                "state",
                "manufacturer",
                "model",
                "version",
                "year",
                "partner",
                "automatic_type",
                "score",
                "coverage",
                "last_seen",
                "external_id",
            ],
        )
        selected = st.selectbox(
            "Abrir revisão",
            [None, *[r["id"] for r in rows]],
            format_func=lambda i: "Selecione um item" if i is None else f"Revisão #{i}",
            key="review_selection",
        )
        if selected is not None:
            detail(service, selected)
    elif page == "Estoque WR Motos":
        table(
            filtered(snapshot["stock"], "stock"),
            "stock",
            [
                "manufacturer",
                "model",
                "year",
                "price",
                "mileage",
                "automatic_type",
                "coverage",
                "priority",
                "external_id",
                "last_seen",
                "source_url",
            ],
        )
    elif page in {"Sem suporte", "Suporte parcial"}:
        status = "SEM_SUPORTE" if page == "Sem suporte" else "SUPORTE_PARCIAL"
        st.caption("Somente anúncios com identidade vinculada e status da base vigente.")
        table(
            filter_rows(snapshot["stock"], {"coverage": [status]}),
            "support",
            [
                "manufacturer",
                "model",
                "year",
                "partner",
                "external_id",
                "source_url",
                "scanner_key",
                "supported_systems",
                "unsupported_systems",
                "analysis_systems",
                "unknown_systems",
                "last_seen",
            ],
        )
    elif page == "Possíveis novas motos":
        st.info("Ausência provável é uma hipótese sobre esta versão da base, não uma confirmação de falta de suporte.")
        for title, rows in service.opportunities().items():
            st.subheader(title)
            table(
                rows,
                title,
                [
                    "id",
                    "manufacturer",
                    "model",
                    "year",
                    "external_id",
                    "priority",
                    "effective_type",
                    "evidence",
                    "source_url",
                ],
            )
    elif page == "Base do Scanner":
        text = st.text_input("Buscar na base", placeholder="Fabricante, modelo, ano ou chave")
        rows = service.scanner(text)
        table(
            rows, "scanner", ["manufacturer", "model", "year", "scanner_key", "status", "system_count", "latest_date"]
        )
        key = st.selectbox("Inspecionar identidade", [None, *[r["key"] for r in rows]], index=0)
        if key:
            moto = next(r for r in rows if r["key"] == key)
            systems(moto)
            st.json(moto, expanded=False)
    elif page == "Busca global":
        text = st.text_input("Buscar em anúncios, fila e scanner", placeholder="Ex.: BMW 2022 ou ID do anúncio")
        if text.strip():
            for name, rows in service.search(text).items():
                st.subheader(name)
                table(
                    rows,
                    name,
                    [
                        "id",
                        "manufacturer",
                        "model",
                        "year",
                        "external_id",
                        "scanner_key",
                        "coverage",
                        "status",
                        "state",
                    ],
                )
    else:
        page_number = st.number_input("Página do histórico", min_value=1, value=1, step=1)
        history = service.history(page_number - 1)
        st.subheader("Coletas · até 30 por página")
        table(
            [
                {
                    "Coleta": c["id"],
                    "Data": c["created_at"],
                    "Estado": c["status"],
                    "Anúncios": c["count"],
                    **c["delta"],
                    "Falhas": len(c["summary"].get("errors", [])),
                }
                for c in history["collections"]
            ],
            "collections",
        )
        st.subheader("Decisões humanas")
        table(history["decisions"], "decisions")
        st.subheader("Ocorrências da fila")
        table(history["occurrences"], "occurrences")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.getLogger(__name__).exception("dashboard_page_failed")
        st.error("Não foi possível carregar esta consulta. Atualize os dados ou consulte o log local.")
