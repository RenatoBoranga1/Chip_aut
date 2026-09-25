"""Operational human labels, direct navigation and existing-memory integration."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_dashboard import command, dump
from test_dashboard import dashboard as dashboard_fixture
from test_matching import motorcycle
from test_review_queue import ad, collect, coverage, import_base

from database.dashboard_repository import DashboardRepository
from database.partner_repository import PartnerRepository
from partners.models import CollectionResult
from services.coverage_service import build_coverage
from services.dashboard_service import DashboardService
from services.review_presentation import decision_link, presentation

dashboard = dashboard_fixture


def row(service, item_id=1):
    return next(r for r in service.snapshot()["queue"] if r["id"] == item_id)


def test_default_is_pending_even_for_exact_supported(dashboard):
    rows = dashboard.snapshot()["stock"]
    assert all(r["human_status"] == "Pendente" for r in rows)
    exact = next(r for r in rows if r["external_id"] == "4")
    assert exact["base_status"] == "Correspondência automática encontrada"
    assert row(dashboard)["base_status"] == "Correspondência ambígua"
    assert row(dashboard)["decision_action"] == "Registrar decisão"


@pytest.mark.parametrize(
    "action,candidate,human,base",
    [
        ("CONFIRMAR_MATCH", "BMW|F900R|2025", "Existe na base", "Existe na base — confirmado"),
        ("NAO_EXISTE_NA_BASE", None, "Não existe na base", "Ausência confirmada"),
        ("DEIXAR_PENDENTE", None, "Em dúvida", "Em dúvida"),
        ("REJEITAR_CANDIDATO", "BMW|F900R|2025", "Pendente", "Pendente de confirmação"),
        ("IGNORAR", None, "Pendente", "Correspondência ambígua"),
    ],
)
def test_human_states_derive_from_existing_decisions(dashboard, action, candidate, human, base):
    command(dashboard, action=action, candidate=candidate)
    r = row(dashboard)
    assert (r["human_status"], r["base_status"]) == (human, base)
    assert r["decision_action"] == "Ver / alterar decisão"
    assert "Ver / alterar decisão" in decision_link(r)
    if action == "NAO_EXISTE_NA_BASE":
        assert r["coverage"] is None
    if action == "DEIXAR_PENDENTE":
        assert r["state"] == "deferred"


@pytest.mark.parametrize("change", ["base", "identity"])
def test_stale_human_label_returns_to_pending_without_writes(dashboard, change):
    command(dashboard, action="NAO_EXISTE_NA_BASE", candidate=None)
    if change == "base":
        import_base(dashboard.config.database, [motorcycle()])
    else:
        collect(dashboard.config.database, [ad(model="R18")])
    before = dump(dashboard.config.database)
    r = row(dashboard)
    assert r["human_status"] == "Pendente"
    assert r["base_status"] == "Pendente de confirmação"
    assert r["decision_action"] == "Ver / alterar decisão"
    assert before == dump(dashboard.config.database)


def test_change_keeps_audit_and_never_creates_development(dashboard):
    command(dashboard, action="NAO_EXISTE_NA_BASE", candidate=None)
    command(dashboard)
    item = dashboard.detail(1)
    assert len(item["history"]) == 2
    assert item["history"][1]["previous_decision_id"] == item["history"][0]["id"]
    assert item["human_decision"]["candidate_key"] == "BMW|F900R|2025"
    assert item["human_decision"]["reviewer"] and item["human_decision"]["created_at"]
    with sqlite3.connect(dashboard.config.database) as db:
        assert db.execute("SELECT COUNT(*) FROM development_items").fetchone()[0] == 0


@pytest.mark.parametrize("candidate", [None, "", "BMW|UNKNOWN|2025", "HONDA|NC750X|2024"])
def test_exists_requires_valid_compatible_link(dashboard, candidate):
    before = dump(dashboard.config.database)
    with pytest.raises(ValueError):
        command(dashboard, candidate=candidate)
    assert dump(dashboard.config.database) == before


@pytest.mark.parametrize(
    "text,brand,year,count",
    [
        ("F900", None, None, 2),
        ("BMW F 900 R GT 2025", "BMW", 2025, 1),
        ("G650", None, None, 1),
        ("missing", None, None, 0),
        ("", "HONDA", None, 0),
        ("", None, 2024, 0),
    ],
)
def test_scanner_search_filters_current_compatible_records(dashboard, text, brand, year, count):
    assert len(dashboard.search_scanner_candidates(1, text, brand, year)) == count


def test_manual_link_outside_fuzzy_candidates_and_next_collection_memory(dashboard, tmp_path):
    assert "BMW|R18|2025" not in {c["scanner_key"] for c in dashboard.detail(1)["automatic"]["candidates"]}
    key = dashboard.search_scanner_candidates(1, "R18")[0]["key"]
    command(dashboard, candidate=key)
    coverage(dashboard.config.database, [ad(collected_at="2026-09-25T12:00:00+00:00")], tmp_path / "next")
    r = row(dashboard)
    assert r["human_status"] == "Existe na base" and r["scanner_key"] == key
    assert r["state"] == "reused"


def test_partner_states_new_known_departed_returned(dashboard):
    path = dashboard.config.database
    assert row(dashboard)["partner_status"] == "Novo anúncio"
    collect(path, [ad()])
    assert row(dashboard)["partner_status"] == "Já conhecido"
    collect(path, [])
    assert row(dashboard)["partner_status"] == "Saiu do estoque"
    collect(path, [ad()])
    assert row(dashboard)["partner_status"] == "Reapareceu"
    assert row(dashboard)["first_seen"] == "2026-09-22T12:00:00+00:00"


@pytest.mark.parametrize("kind", ["partial", "failed", "cached"])
def test_noncomplete_never_invents_departure(dashboard, kind):
    path = dashboard.config.database
    with PartnerRepository(path) as repo:
        repo.save_collection(
            CollectionResult(
                "wr_motos",
                "2026-09-25T12:00:00+00:00",
                advertisements=[ad(external_id="99")] if kind == "partial" else [],
                cached=kind == "cached",
            )
        )
    assert row(dashboard)["partner_status"] != "Saiu do estoque"


def test_reused_pipeline_is_known_not_perpetually_new(dashboard):
    with sqlite3.connect(dashboard.config.database) as db:
        db.execute(
            "INSERT INTO pipeline_runs(started_at,heartbeat_at,trigger_type,status,config_hash,collection_run_id,summary_json) VALUES ('now','now','manual','SUCCESS','fixture',1,'{\"reused\":true}')"
        )
    assert row(dashboard)["partner_status"] == "Já conhecido"


def test_partner_ids_and_decisions_do_not_leak(dashboard, tmp_path):
    other = DashboardService(replace(dashboard.config, partner="fixture_partner"))
    with PartnerRepository(dashboard.config.database) as repo:
        cid = repo.save_collection(
            CollectionResult(
                "fixture_partner", "2026-09-25T12:00:00+00:00", [ad(partner="fixture_partner")], complete=True
            )
        )
    build_coverage(cid, dashboard.config.database, tmp_path / "other")
    command(dashboard)
    assert other.snapshot()["queue"][0]["human_status"] == "Pendente"
    assert other.snapshot()["queue"][0]["partner_status"] == "Novo anúncio"
    with pytest.raises(ValueError):
        other.search_scanner_candidates(1)
    assert "partner=fixture_partner" in decision_link(other.snapshot()["queue"][0])


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("NAO_ENCONTRADA_NA_BASE", "Não encontrado automaticamente"),
        ("AMBIGUOUS", "Correspondência ambígua"),
        ("CORRESPONDENCIA_PROVAVEL", "Correspondência aproximada"),
        ("REVISAR", "Identidade exige revisão"),
    ],
)
def test_pending_origin_uses_evidence(kind, reason):
    result = {"match_type": kind, "requires_review": True, "scanner_status": "SEM_SUPORTE"}
    r = presentation(result, result, partner_state="Novo anúncio")
    assert "Novo anúncio do parceiro" in r["pending_origin"] and reason in r["pending_origin"]
    assert "Sem suporte" not in r["pending_origin"]
    assert r["human_status"] == "Pendente"


@pytest.fixture
def ui(dashboard, monkeypatch):
    monkeypatch.setenv("MOTO_DB", str(dashboard.config.database))
    monkeypatch.setenv("MOTO_READ_ONLY", "0")
    return AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30)


@pytest.mark.parametrize("page", ["Fila de revisão", "Possíveis novas motos"])
def test_main_tables_are_simple_with_real_action_link(ui, page):
    ui.run().radio(key="navigation").set_value(page).run()
    assert not ui.exception and not ui.error
    tables = [t.value for t in ui.table if "Decisão humana" in t.value.columns]
    assert tables
    for table in tables:
        assert "Cobertura" not in table.columns and "Prioridade" not in table.columns
        assert table.columns[-1] == "Ação"
        assert all("?review=" in link for link in table["Ação"])


def test_direct_route_preloads_item_and_search_then_saves(ui, dashboard):
    ui.query_params.update(review="1", partner="wr_motos")
    ui.run()
    assert not ui.error and ui.title[0].value == "Registrar decisão humana"
    assert ui.selectbox(key="candidate_1").value is None
    ui.checkbox(key="search_scanner_1").check().run()
    ui.text_input(key="search_text_1").set_value("R18").run()
    assert ui.selectbox(key="candidate_1").value is None
    ui.selectbox(key="candidate_1").set_value("BMW|R18|2025")
    ui.text_input(key="reviewer_1").set_value("Fixture")
    ui.text_area(key="note_1").set_value("Correspondência conferida manualmente")
    next(b for b in ui.button if b.label == "Salvar decisão").click().run()
    assert not ui.error and ui.success
    assert row(dashboard)["human_status"] == "Existe na base"
    assert dashboard.detail(1)["priority"] and dashboard.detail(1)["systems"]


@pytest.mark.parametrize("id,partner", [("bad", "wr_motos"), ("999", "wr_motos"), ("1", "other")])
def test_invalid_direct_link_cannot_open_wrong_review(ui, id, partner):
    ui.query_params.update(review=id, partner=partner)
    ui.run()
    assert ui.error and not ui.exception


def test_direct_read_only_has_no_save(ui, monkeypatch):
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    ui.query_params.update(review="1", partner="wr_motos")
    ui.run()
    assert not ui.error and not ui.exception
    assert not any(b.label == "Salvar decisão" for b in ui.button)


def test_labels_read_only_and_existing_schema(dashboard):
    before = dump(dashboard.config.database)
    dashboard.snapshot()
    dashboard.detail(1)
    dashboard.opportunities()
    assert dump(dashboard.config.database) == before
    with DashboardRepository(dashboard.config.database) as repo:
        assert repo.connection.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 11
        assert repo.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_doubt_stays_in_operational_opportunities(dashboard):
    command(dashboard, item_id=4, action="DEIXAR_PENDENTE", candidate=None)
    rows = dashboard.opportunities()["Ainda em revisão"]
    assert any(r["id"] == 4 and r["human_status"] == "Em dúvida" for r in rows)


def test_new_alert_explains_partner_not_scanner():
    from services.alert_service import event
    from ui.textos import ALERT_TYPES

    alert = event("NOVO_ANUNCIO", "fixture", {})
    assert alert["title"] == "Novo anúncio no parceiro"
    assert ALERT_TYPES["NOVO_ANUNCIO"] == "Novo anúncio no parceiro"


@pytest.mark.parametrize("action", ["NAO_EXISTE_NA_BASE", "DEIXAR_PENDENTE"])
def test_direct_absence_and_doubt(ui, dashboard, action):
    from ui.textos import ACTIONS

    ui.query_params.update(review="1", partner="wr_motos")
    ui.run()
    label = next(label for label, code in ACTIONS.items() if code == action)
    ui.selectbox(key="action_1").set_value(label)
    ui.text_input(key="reviewer_1").set_value("Fixture")
    ui.text_area(key="note_1").set_value("Revisão explícita de teste")
    next(b for b in ui.button if b.label == "Salvar decisão").click().run()
    assert not ui.error and ui.success
    item = dashboard.detail(1)
    assert item["human_decision"]["action"] == action
    assert item["effective"]["scanner_status"] is None
