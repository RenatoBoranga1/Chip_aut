"""Sidebar presentation policy; hidden routes remain available to internal actions."""

from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True)
class NavigationItem:
    key: str
    label: str
    visible: bool
    order: int


# Keys retain the dashboard's existing identifiers. Toggle visibility to restore a page.
NAVIGATION_ITEMS = (
    NavigationItem("Visão geral", "Visão geral", True, 1),
    NavigationItem("Indicadores gerenciais", "Indicadores gerenciais", True, 2),
    NavigationItem("Possíveis novas motos", "Possíveis novas motos", True, 3),
    NavigationItem("Fila de revisão", "Fila de revisão", True, 4),
    NavigationItem("Sem suporte", "Sem suporte", True, 5),
    NavigationItem("Suporte parcial", "Suporte parcial", True, 6),
    NavigationItem("Histórico", "Histórico", True, 7),
    NavigationItem("Atualização automática", "Atualização automática", True, 8),
    NavigationItem("Alertas", "Alertas", True, 9),
    NavigationItem("Parceiros", "Parceiros", True, 10),
    NavigationItem("Atualização da base do scanner", "Atualização da base do scanner", True, 11),
    NavigationItem("Estoque", "Estoque", False, 12),
    NavigationItem("Base do scanner", "Base do scanner", False, 13),
    NavigationItem("Busca global", "Busca global", False, 14),
    NavigationItem("Priorização operacional", "Priorização operacional", False, 15),
    NavigationItem("Motos para desenvolvimento", "Motos para desenvolvimento", False, 16),
)
PAGES = [item.key for item in NAVIGATION_ITEMS]
HOME = "Visão geral"


def menu_items(stock_page):
    return [
        (
            stock_page if item.key == "Estoque" else item.key,
            stock_page if item.key == "Estoque" and item.label == "Estoque" else item.label,
        )
        for item in sorted(NAVIGATION_ITEMS, key=lambda item: item.order)
        if item.visible
    ]


def request_navigation(page):
    """Explicit internal links may open a hidden page without exposing it in the menu."""
    st.session_state["_navigation_request"] = page


def clear_internal():
    st.session_state.pop("_navigation_internal", None)


def go_home():
    clear_internal()
    st.session_state["navigation"] = HOME


def resolve_navigation(state, stock_page):
    visible = dict(menu_items(stock_page))
    known = {stock_page if key == "Estoque" else key for key in PAGES}
    signature = tuple((i.key, i.label, i.visible, i.order) for i in NAVIGATION_ITEMS)
    if state.get("_navigation_policy") != signature:
        state.pop("_navigation_internal", None)
    state["_navigation_policy"] = signature
    if state.get("navigation") not in visible:
        state["navigation"] = HOME
        state.pop("_navigation_internal", None)
    requested = state.pop("_navigation_request", None)
    if requested in known:
        state.pop("_navigation_internal", None)
        if requested in visible:
            state["navigation"] = requested
        else:
            state["_navigation_internal"] = requested
    internal = state.get("_navigation_internal")
    if internal not in known:
        state.pop("_navigation_internal", None)
    return state.get("_navigation_internal", state["navigation"])


def sidebar_navigation(stock_page):
    page = resolve_navigation(st.session_state, stock_page)
    labels = dict(menu_items(stock_page))
    selected = st.sidebar.radio(
        "Navegação", list(labels), format_func=labels.__getitem__, key="navigation", on_change=clear_internal
    )
    if "_navigation_internal" in st.session_state:
        if st.button("Voltar à Visão geral", key="navigation_home", on_click=go_home):
            st.rerun()
        return page
    return selected
