import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_matching import motorcycle
from test_review_queue import ad, collect, coverage, import_base

from database.dashboard_repository import DashboardRepository
from services.dashboard_service import DashboardConfig, DashboardService, filter_rows


@pytest.fixture
def dashboard(tmp_path):
    path = tmp_path / "dashboard.sqlite3"
    motos = [
        motorcycle(),
        motorcycle("F 900 R GT"),
        motorcycle("G 650 GS", status="SEM_SUPORTE"),
        motorcycle("NC 750 X", manufacturer="HONDA", year=2024, status="SUPORTE_PARCIAL"),
        motorcycle("R 18", status="SUPORTADO"),
    ]
    import_base(path, motos)
    ads = [
        ad(),
        ad(external_id="2", model="G 650 GS"),
        ad(external_id="3", manufacturer="HONDA", model="NC 750 X", year=2024),
        ad(external_id="4", model="R 18"),
        ad(external_id="5", year=2023),
    ]
    coverage(path, ads, tmp_path / "reports")
    return DashboardService(DashboardConfig(path))


def command(service, item_id=1, action="CONFIRMAR_MATCH", candidate="BMW|F900R|2025", token=None, revision=None):
    return service.submit(
        item_id,
        action,
        "Fixture reviewer",
        "Fixture note",
        candidate,
        token or str(uuid.uuid4()),
        revision or service.detail(item_id)["revision"],
    )


def dump(path):
    with sqlite3.connect(path) as db:
        return list(db.iterdump())


def test_read_only_queries_do_not_change_any_table(dashboard):
    before = dump(dashboard.config.database)
    snapshot = dashboard.snapshot()
    dashboard.detail(1)
    dashboard.search("BMW")
    dashboard.history()
    dashboard.opportunities()
    assert dump(dashboard.config.database) == before
    assert len(snapshot["stock"]) == 5 and len(snapshot["queue"]) == 4
    assert snapshot["matching"] == {"AMBIGUOUS": 1, "EXATO_NORMALIZADO": 3, "NAO_ENCONTRADA_NA_BASE": 1}
    assert snapshot["coverage"]["SEM_SUPORTE"] == 1
    assert snapshot["coverage"]["SUPORTE_PARCIAL"] == 1
    assert snapshot["priorities"] == {"medium": 1, "high": 3}


def test_queries_omit_raw_html_and_history_payloads(dashboard):
    with DashboardRepository(dashboard.config.database) as repo:
        assert all("raw_data" not in a and "raw_text" not in a for a in repo.advertisements("wr_motos"))
        assert all("raw_data" not in i["advertisement"] for i in repo.queue("wr_motos"))
        assert "raw_data" not in repo.detail(1, "wr_motos")["advertisement"]
        with pytest.raises(sqlite3.OperationalError):
            repo.connection.execute("DELETE FROM imports")


def test_latest_collection_warnings_are_not_accumulated_from_history(dashboard):
    collect(dashboard.config.database, [ad(parse_warnings=["MISSING_PRICE", "UNKNOWN_YEAR"])])
    assert dashboard.snapshot()["latest"]["warnings"] == {"MISSING_PRICE": 1, "UNKNOWN_YEAR": 1}
    collect(dashboard.config.database, [ad()])
    assert dashboard.snapshot()["latest"]["warnings"] == {}


@pytest.mark.parametrize(
    "field,value,count",
    [
        ("priority", "high", 3),
        ("state", "pending", 4),
        ("manufacturer", "HONDA", 1),
        ("year", 2024, 1),
        ("automatic_type", "AMBIGUOUS", 1),
        ("coverage", "SEM_SUPORTE", 1),
        ("partner", "missing", 0),
    ],
)
def test_queue_filters(dashboard, field, value, count):
    assert len(filter_rows(dashboard.snapshot()["queue"], {field: [value]})) == count


@pytest.mark.parametrize(
    "text,count", [("BMW 2025", 2), ("F 900", 2), ("BMW|G650GS|2025", 1), ("5", 4), ("DOES NOT EXIST", 0)]
)
def test_free_text_search(dashboard, text, count):
    assert len(filter_rows(dashboard.snapshot()["queue"], text=text)) == count


def test_sort_orders():
    rows = [
        {"id": 1, "priority": "low", "last_seen": "2024", "manufacturer": "Z"},
        {"id": 2, "priority": "high", "last_seen": "2025", "manufacturer": "A"},
    ]
    for mode, expected in [("priority", 2), ("recent", 2), ("oldest", 1), ("model", 2)]:
        assert filter_rows(rows, sort=mode)[0]["id"] == expected


@pytest.mark.parametrize(
    "action,candidate,kind,state",
    [
        ("CONFIRMAR_MATCH", "BMW|F900R|2025", "EXATO_CONFIRMADO_HUMANAMENTE", "resolved"),
        ("REJEITAR_CANDIDATO", "BMW|F900R|2025", "REVISAR", "pending"),
        ("NAO_EXISTE_NA_BASE", None, "CONFIRMADO_AUSENTE_NA_BASE", "resolved"),
        ("DEIXAR_PENDENTE", None, "AMBIGUOUS", "deferred"),
        ("IGNORAR", None, "AMBIGUOUS", "ignored"),
    ],
)
def test_actions_use_existing_engine_and_preserve_automatic(dashboard, action, candidate, kind, state):
    before = dashboard.detail(1)["automatic"]
    command(dashboard, action=action, candidate=candidate)
    after = dashboard.detail(1)
    assert after["automatic"] == before
    assert after["effective"]["match_type"] == kind and after["state"] == state
    assert after["history"][-1]["before_state"] == "pending"
    assert after["history"][-1]["after_state"] == state
    if action == "NAO_EXISTE_NA_BASE":
        assert after["effective"]["scanner_status"] is None
        assert dashboard.snapshot()["coverage"]["CONFIRMADO_AUSENTE_NA_BASE"] == 1
    if action == "CONFIRMAR_MATCH":
        assert after["effective"]["scanner_status"] == "SEM_STATUS"
        assert dashboard.snapshot()["coverage"]["SEM_STATUS"] == 1


def test_double_submission_returns_one_decision(dashboard):
    token, rev = str(uuid.uuid4()), dashboard.detail(1)["revision"]
    command(dashboard, token=token, revision=rev)
    assert command(dashboard, token=token, revision=rev)["submission_replayed"]
    assert len(dashboard.detail(1)["history"]) == 1
    with pytest.raises(ValueError, match="outros dados"):
        command(dashboard, token=token, revision=rev, action="IGNORAR", candidate=None)


def test_parallel_double_submission_is_atomic(dashboard):
    token, rev = str(uuid.uuid4()), dashboard.detail(1)["revision"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: command(dashboard, token=token, revision=rev), range(2)))
    assert sum(r.get("submission_replayed", False) for r in results) == 1
    assert len(dashboard.detail(1)["history"]) == 1


@pytest.mark.parametrize("change", ["decision", "base", "collection"])
def test_old_form_refuses_concurrent_changes(dashboard, tmp_path, change):
    rev = dashboard.detail(1)["revision"]
    if change == "decision":
        command(dashboard, action="DEIXAR_PENDENTE", candidate=None)
    elif change == "base":
        import_base(dashboard.config.database, [motorcycle()])
    else:
        coverage(dashboard.config.database, [ad()], tmp_path / "new")
    with pytest.raises(ValueError, match="mudou"):
        command(dashboard, revision=rev)


def test_stale_preview_does_not_write_events(dashboard):
    command(dashboard, action="NAO_EXISTE_NA_BASE", candidate=None)
    import_base(dashboard.config.database, [motorcycle()])
    before = dump(dashboard.config.database)
    assert dashboard.detail(1)["stale_reason"] == "STALE_BASE_VERSION"
    assert dashboard.snapshot()["states"]["invalidated"] >= 1
    assert dump(dashboard.config.database) == before


def test_collected_identity_change_blocks_decision_before_coverage(dashboard):
    command(dashboard)
    old_revision = dashboard.detail(1)["revision"]
    collect(dashboard.config.database, [ad(model="F 900 R GT")])
    before = dump(dashboard.config.database)
    assert dashboard.detail(1)["state"] == "invalidated"
    with pytest.raises(ValueError, match="mudou"):
        command(dashboard, revision=old_revision)
    with pytest.raises(ValueError, match="Gere a cobertura"):
        command(dashboard)
    assert dump(dashboard.config.database) == before


def test_positive_memory_current_support_is_read_from_latest_base(dashboard):
    command(dashboard)
    import_base(dashboard.config.database, [motorcycle(status="SEM_SUPORTE")])
    item = dashboard.detail(1)
    assert item["systems"]["status"] == "SEM_SUPORTE"
    assert dashboard.snapshot()["stock"][0]["coverage"] == "SEM_SUPORTE"


def test_missing_database_not_created(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(ValueError):
        DashboardService(DashboardConfig(path)).snapshot()
    assert not path.exists()


def test_read_only_and_partner_scope_block_writes(dashboard):
    ro = DashboardService(replace(dashboard.config, read_only=True))
    with pytest.raises(ValueError, match="leitura"):
        command(ro)
    other = DashboardService(replace(dashboard.config, partner="other"))
    with pytest.raises(ValueError):
        other.detail(1)
    with pytest.raises(ValueError):
        other.submit(1, "IGNORAR", "Fixture", "note", None, "request", "revision")
    assert dashboard.detail(1)["history"] == []


def test_validation_error_preserves_database(dashboard):
    before = dump(dashboard.config.database)
    with pytest.raises(ValueError):
        dashboard.submit(1, "CONFIRMAR_MATCH", "", "", None, "request", dashboard.detail(1)["revision"])
    assert dump(dashboard.config.database) == before


def test_history_is_paginated_and_includes_transitions(dashboard):
    command(dashboard)
    h = dashboard.history()
    assert h["collections"][0]["count"] == 5
    assert len(h["occurrences"]) == 4
    assert h["decisions"][0]["after_state"] == "resolved"
    assert dashboard.history(1) == {"collections": [], "decisions": [], "occurrences": []}


def test_opportunities_keep_hypothesis_separate(dashboard):
    rows = dashboard.opportunities()
    assert len(rows["Provável ausência"]) == 1
    assert len(rows["Confirmado ausente"]) == 0
    assert rows["Provável ausência"][0]["evidence"]
    command(dashboard, item_id=4, action="NAO_EXISTE_NA_BASE", candidate=None)
    assert len(dashboard.opportunities()["Confirmado ausente"]) == 1


def test_global_search_all_three_sources(dashboard):
    r = dashboard.search("F 900")
    assert r["Anúncios"] and r["Fila"] and r["Scanner"]


def test_ui_has_no_sql_or_domain_matching():
    code = Path("app/dashboard.py").read_text(encoding="utf-8")
    assert "sqlite3" not in code and ".execute(" not in code and "Matcher(" not in code


@pytest.fixture
def ui(dashboard, monkeypatch):
    monkeypatch.setenv("MOTO_DB", str(dashboard.config.database))
    monkeypatch.setenv("MOTO_READ_ONLY", "0")
    return AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=20).run()


@pytest.mark.parametrize(
    "page",
    [
        "Visão geral",
        "Fila de revisão",
        "Estoque WR Motos",
        "Sem suporte",
        "Suporte parcial",
        "Possíveis novas motos",
        "Base do scanner",
        "Busca global",
        "Histórico",
    ],
)
def test_streamlit_page_smoke(ui, page):
    ui.radio(key="navigation").set_value(page).run()
    assert not ui.exception and not ui.error
    assert ui.title[0].value == page


def test_streamlit_confirmation_updates_effective_and_home(ui, dashboard):
    ui.radio(key="navigation").set_value("Fila de revisão").run()
    ui.selectbox(key="review_selection").set_value(1).run()
    assert not ui.exception and not ui.error
    ui.selectbox(key="candidate_1").set_value("BMW|F900R|2025")
    ui.text_input(key="reviewer_1").set_value("Fixture UI")
    ui.text_area(key="note_1").set_value("Fixture identity checked")
    next(b for b in ui.button if b.label == "Salvar decisão").click().run()
    assert not ui.exception and not ui.error and ui.success
    assert dashboard.detail(1)["effective"]["match_type"] == "EXATO_CONFIRMADO_HUMANAMENTE"
    ui.run()
    assert len(dashboard.detail(1)["history"]) == 1
    ui.radio(key="navigation").set_value("Visão geral").run()
    assert not ui.error


def test_streamlit_validation_error_is_visible_without_success(ui, dashboard):
    ui.radio(key="navigation").set_value("Fila de revisão").run()
    ui.selectbox(key="review_selection").set_value(1).run()
    next(b for b in ui.button if b.label == "Salvar decisão").click().run()
    assert ui.error and not ui.success and not ui.exception
    assert dashboard.detail(1)["history"] == []
