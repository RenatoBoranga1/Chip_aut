"""Complete V16 diagnostics and review flow without changing the operational database."""

import json
import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_application_base import (
    application,
    content,
    parse,
)
from test_application_base import scanner as scanner_fixture
from test_scanner_versions import publish

from scanner_base.adapters import conflict_diagnostics
from services.dashboard_service import DashboardConfig, DashboardService
from services.scanner_service import ScannerService


@pytest.fixture
def scanner(tmp_path):
    return scanner_fixture.__wrapped__(tmp_path)


def variants():
    return [
        application(),
        application(),
        application(**{"VÍDEO": "NÃO"}),
        application(**{"TABELA FIPE": "Verificar nome"}),
    ]


def test_conflicts_count_distinct_keys_not_variant_rows():
    base, _, report, _ = parse(variants())
    assert len(base.motorcycles) == 1 and len(base.records) == 4
    assert report["duplicates"] == 1
    assert report["application_variant_rows"] == 2
    assert report["application_conflicts"] == report["conflicts"] == 1
    assert report["support_conflicts"] == 0 and report["publishable"]
    assert base.records[-1].raw_fields["fipe"] == "Verificar nome"


def test_conflicts_distinguish_cables_and_support():
    _, _, report, _ = parse(variants() + [application(CABO="C2"), application(CABO="C2", **{"VÍDEO": "NÃO"})])
    assert report["application_conflicts"] == 2
    summary = conflict_diagnostics([{"code": "CONFLICTING_SYSTEM"}])
    assert summary["conflicts"] == summary["support_conflicts"] == 1
    assert summary["application_conflicts"] == 0


def test_five_systems_multiple_versions_and_cables_are_one_vehicle():
    rows = [application(SISTEMA=f"Sistema {i}", **{"VERS.": f"V{i}.0"}) for i in range(1, 6)]
    rows += [application(SISTEMA="Sistema 1", CABO="C2", **{"VERS.": "V16.0"})]
    base, _, report, _ = parse(rows)
    assert report["unique_vehicles"] == 1 and report["applications"] == 6
    assert base.motorcycles[0].system_count == 5
    assert report["conflicts"] == report["duplicates"] == 0
    assert all(r.status == "SEM_STATUS" for r in base.records)


def test_unknown_workbook_is_rejected_with_clear_message():
    with pytest.raises(ValueError, match="estrutura obrigatória"):
        parse(headers=["QUALQUER CAMPO"], title="Desconhecido")


@pytest.mark.parametrize("published", [False, True])
def test_historical_diagnostics_corrected_without_database_writes(scanner, published):
    version = scanner.prepare(content(variants()), "v16.xlsx", "Fixture")["id"]
    if published:
        publish(scanner, version)
    with sqlite3.connect(scanner.database) as db:
        report = json.loads(db.execute("SELECT report_json FROM scanner_versions WHERE id=?", (version,)).fetchone()[0])
        for key in ("application_conflicts", "support_conflicts", "application_variant_rows"):
            report.pop(key)
        report["conflicts"] = 0
        db.execute("UPDATE scanner_versions SET report_json=? WHERE id=?", (json.dumps(report), version))
        if published:
            # Administrative versions may not have a staging payload; import_issues is retained.
            db.execute("UPDATE scanner_versions SET payload_json=NULL WHERE id=?", (version,))
        db.commit()
        before = list(db.iterdump())
    readonly = ScannerService(scanner.database, read_only=True)
    detail = readonly.detail(version)
    assert detail["report"]["conflicts"] == 1 and detail["diagnostics_recomputed"]
    with sqlite3.connect(scanner.database) as db:
        assert list(db.iterdump()) == before


def test_staging_keeps_conflicts_and_explicit_confirmation(scanner):
    version = scanner.prepare(content(variants()), "v16.xlsx", "Fixture")["id"]
    detail = scanner.detail(version)
    assert detail["report"]["conflicts"] == 1
    with pytest.raises(ValueError, match="Confirmação explícita"):
        scanner.publish(version, "Fixture", "Revisado")
    with sqlite3.connect(scanner.database) as db:
        assert db.execute("SELECT MAX(id) FROM imports").fetchone()[0] == 1
    publish(scanner, version)
    dashboard = DashboardService(DashboardConfig(scanner.database))
    rows = dashboard.scanner("ABS MX-C1")
    assert len(rows) == 1 and rows[0]["application_count"] == 4 and rows[0]["system_count"] == 1
    assert len(dashboard.scanner_applications(rows[0]["key"])) == 4
    assert scanner.detail(version)["report"]["conflicts"] == 1


def test_confirmation_summary_and_internal_vehicle_detail(scanner, monkeypatch):
    version = scanner.prepare(content(variants()), "v16.xlsx", "Fixture")["id"]
    publish(scanner, version)
    pending = scanner.prepare(content(variants() + [application(SISTEMA="INJEÇÃO")]), "next.xlsx", "Fixture")["id"]
    monkeypatch.setenv("MOTO_DB", str(scanner.database))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    app = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    app.radio(key="navigation").set_value("Atualização da base do scanner").run()
    app.selectbox(key="scanner_version_choice").set_value(pending).run()
    summary = next(t.value for t in app.table if "Duplicidades exatas" in t.value.columns)
    assert summary.iloc[0]["Veículos"] == 1
    assert summary.iloc[0]["Aplicações (linhas)"] == 5
    assert summary.iloc[0]["Conflitos"] == 1
    assert any("Existem conflitos" in w.value for w in app.warning)
    next(b for b in app.button if b.label == "Consultar veículos da base ativa").click().run()
    assert not app.exception and not app.error
    assert "Base do scanner" not in app.radio(key="navigation").options
    assert app.title[0].value == "Base do scanner"
    next(t for t in app.text_input if t.label == "Buscar na base").set_value("ABS MX-C1").run()
    next(t for t in app.selectbox if t.label == "Inspecionar identidade").set_value("BMW|F900R|2025").run()
    assert not app.exception and not app.error
    table = next(t.value for t in app.dataframe if "Cabo" in t.value.columns)
    assert "Verificar nome" in table["FIPE"].values
    assert "Versão de introdução da aplicação" in table.columns
