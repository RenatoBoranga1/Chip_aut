"""Default sidebar policy and intentional internal navigation contracts."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_dashboard import dashboard as dashboard_fixture

from ui import navigation

VISIBLE = [
    "Visão geral",
    "Indicadores gerenciais",
    "Assistente de IA",
    "Possíveis novas motos",
    "Fila de revisão",
    "Sem suporte",
    "Suporte parcial",
    "Histórico",
    "Atualização automática",
    "Alertas",
    "Parceiros",
    "Atualização da base do scanner",
]
HIDDEN = [
    "Estoque WR Motos",
    "Base do scanner",
    "Busca global",
    "Priorização operacional",
    "Motos para desenvolvimento",
]


@pytest.fixture
def dashboard(tmp_path):
    return dashboard_fixture.__wrapped__(tmp_path)


@pytest.fixture
def app(dashboard, monkeypatch):
    monkeypatch.setenv("MOTO_DB", str(dashboard.config.database))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    return AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30)


def test_exact_visible_order_labels_and_third_item(app):
    app.run()
    assert not app.exception and not app.error
    assert app.radio(key="navigation").options == VISIBLE
    assert app.radio(key="navigation").options[2] == "Assistente de IA"
    assert app.radio(key="navigation").options[3] == "Possíveis novas motos"
    assert not set(HIDDEN) & set(app.radio(key="navigation").options)


@pytest.mark.parametrize("page", HIDDEN + ["Rota antiga inválida"])
def test_stale_hidden_session_returns_home(app, page):
    app.session_state["navigation"] = page
    app.run()
    assert not app.exception and not app.error
    assert app.title[0].value == "Visão geral"
    assert app.radio(key="navigation").value == "Visão geral"
    assert app.radio(key="navigation").options == VISIBLE


@pytest.mark.parametrize("page", HIDDEN)
def test_internal_hidden_pages_remain_functional_without_menu_entry(app, dashboard, page):
    with sqlite3.connect(dashboard.config.database) as db:
        before = list(db.iterdump())
    app.run()
    app.session_state["_navigation_request"] = page
    app.run()
    assert not app.exception and not app.error
    assert app.title[0].value == page
    assert app.radio(key="navigation").options == VISIBLE
    app.run()  # Retain the internal page on a widget rerun.
    assert app.title[0].value == page
    app.button(key="navigation_home").click().run()
    assert app.title[0].value == "Visão geral"
    with sqlite3.connect(dashboard.config.database) as db:
        assert list(db.iterdump()) == before


def test_selecting_visible_page_leaves_internal_page(app):
    app.run()
    app.session_state["_navigation_request"] = "Base do scanner"
    app.run()
    app.radio(key="navigation").set_value("Possíveis novas motos").run()
    assert not app.exception
    assert app.title[0].value == "Possíveis novas motos"


def test_config_can_restore_relabel_reorder_without_changing_identifiers(monkeypatch):
    monkeypatch.setattr(
        navigation,
        "NAVIGATION_ITEMS",
        tuple(
            replace(i, visible=True, order=0, label="Consulta técnica") if i.key == "Base do scanner" else i
            for i in navigation.NAVIGATION_ITEMS
        ),
    )
    assert navigation.menu_items("Estoque WR Motos")[0] == ("Base do scanner", "Consulta técnica")
    state = {"navigation": "Base do scanner"}
    assert navigation.resolve_navigation(state, "Estoque WR Motos") == "Base do scanner"


def test_policy_change_redirects_previously_open_page(monkeypatch):
    defaults = navigation.NAVIGATION_ITEMS
    monkeypatch.setattr(navigation, "NAVIGATION_ITEMS", tuple(replace(i, visible=True) for i in defaults))
    state = {"navigation": "Base do scanner"}
    assert navigation.resolve_navigation(state, "Estoque WR Motos") == "Base do scanner"
    monkeypatch.setattr(navigation, "NAVIGATION_ITEMS", defaults)
    assert navigation.resolve_navigation(state, "Estoque WR Motos") == "Visão geral"


def test_existing_internal_callbacks_use_explicit_navigation(monkeypatch):
    from ui.alert_panel import navigate
    from ui.development_panel import open_item

    # Streamlit's real session supports attributes; use a compatible test state.
    class State(dict):
        def __setattr__(self, key, value):
            self[key] = value

    state = State()
    monkeypatch.setattr(navigation.st, "session_state", state)
    open_item(12)
    assert navigation.resolve_navigation(state, "Estoque WR Motos") == "Motos para desenvolvimento"
    assert state["development_selection"] == 12
    navigate("Priorização operacional", "priority_selection", 8)
    assert navigation.resolve_navigation(state, "Estoque WR Motos") == "Priorização operacional"
    assert state["priority_selection"] == 8
    navigate("Fila de revisão", "related_review_id", 1)
    assert navigation.resolve_navigation(state, "Estoque WR Motos") == "Fila de revisão"


def test_existing_review_url_still_opens_and_returns_to_queue(app):
    app.query_params.update(review="1", partner="wr_motos")
    app.run()
    assert not app.exception and not app.error
    assert app.title[0].value == "Registrar decisão humana"
    next(b for b in app.button if b.label == "Voltar à fila de revisão").click().run()
    assert not app.exception and not app.error
    assert app.title[0].value == "Fila de revisão"
    assert app.radio(key="navigation").options == VISIBLE


def test_running_session_redirects_after_visibility_change(app, monkeypatch):
    defaults = navigation.NAVIGATION_ITEMS
    monkeypatch.setattr(navigation, "NAVIGATION_ITEMS", tuple(replace(i, visible=True) for i in defaults))
    app.run().radio(key="navigation").set_value("Base do scanner").run()
    assert app.title[0].value == "Base do scanner"
    monkeypatch.setattr(navigation, "NAVIGATION_ITEMS", defaults)
    app.run()
    assert not app.exception and not app.error
    assert app.title[0].value == "Visão geral"
    assert app.radio(key="navigation").options == VISIBLE
