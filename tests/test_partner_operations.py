"""Realistic fixtures, no credentials, public requests or operational databases."""

import csv
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
import requests
from openpyxl import Workbook
from streamlit.testing.v1 import AppTest
from test_matching import motorcycle
from test_review_queue import import_base

from app.partners import main
from database.inventory_repository import read_operations
from partners.authenticated_source import FakeAuthenticatedSource, SourceError, collect_authenticated
from partners.integration import integration
from services.ai_assistant_service import AIAssistantService
from services.ai_context_service import new_conversation
from services.ai_provider import AssistantConfig
from services.dashboard_service import DashboardConfig, DashboardService
from services.motonil_staging_service import MotonilStagingService
from services.partner_inventory_import import FIELDS, PartnerInventoryImportService, preview_file


def rows():
    return [
        dict(external_id="stock-1", manufacturer="BMW", model="F 900 R", year=2025),
        dict(external_id="stock-2", manufacturer="BMW", model="Modelo novo", year=2025),
    ]


def file_bytes(data=None, kind="csv"):
    data = rows() if data is None else data
    if kind == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(data)
        return buffer.getvalue().encode("utf-8")
    book = Workbook()
    sheet = book.active
    sheet.append(list(FIELDS))
    for row in data:
        sheet.append([row.get(k) for k in FIELDS])
    buffer = io.BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


@pytest.mark.parametrize("empty_zip", [False, True])
def test_corrupt_xlsx_reports_validation_error_without_writing(database, empty_zip):
    buffer = io.BytesIO()
    if empty_zip:
        with zipfile.ZipFile(buffer, "w"):
            pass
    else:
        buffer.write(b"not an xlsx file")
    before = database.read_bytes()
    with pytest.raises(ValueError, match="inválida ou corrompida"):
        PartnerInventoryImportService(database).preview("thomas_motos", buffer.getvalue(), "stock.xlsx")
    assert database.read_bytes() == before


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.delenv("MOTO_READ_ONLY", raising=False)
    path = tmp_path / "operation.sqlite3"
    import_base(path, [motorcycle()])
    return path


def confirm(path, partner="thomas_motos", data=None, kind="csv", **kwargs):
    return PartnerInventoryImportService(path).confirm(
        partner,
        file_bytes(data, kind),
        "authorized." + kind,
        reviewer="Operador teste",
        confirmed=True,
        authorized=True,
        motorcycles_confirmed=True,
        **kwargs,
    )


def staged(identifier="1", title="Oferta original"):
    return {
        "external_id": identifier,
        "title": title,
        "source_url": "https://www.motonil.com.br/MOTOS/item-" + identifier,
        "source_category": "65/MOTOS",
    }


@pytest.mark.parametrize("partner", ["thomas_motos", "moto_marques"])
@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_import_preview_confirm_matching_review_and_idempotence(database, partner, kind):
    service = PartnerInventoryImportService(database)
    before = database.read_bytes()
    content = file_bytes(kind=kind)
    preview = service.preview(partner, content, "stock." + kind)
    assert preview["valid_rows"] == 2 and not preview["invalid_rows"]
    assert database.read_bytes() == before
    options = dict(reviewer="Teste", confirmed=True, authorized=True, motorcycles_confirmed=True)
    first = service.confirm(partner, content, "authorized." + kind, **options)
    assert service.confirm(partner, content, "authorized." + kind, **options)["reused"]
    data = DashboardService(DashboardConfig(database, partner)).snapshot()
    assert len(data["stock"]) == len(data["queue"]) == 2
    assert data["matching"]["EXATO_NORMALIZADO"] == 1
    state = read_operations(database)
    assert len(state["imports"]) == 1 and state["imports"][0]["file_hash"] == preview["file_hash"]
    assert state["imports"][0]["filename"] == "authorized." + kind
    assert first["collection_id"]
    with sqlite3.connect(database) as db:
        assert db.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert db.execute("select count(*) from motorcycles").fetchone()[0] == 1


def test_mapping_profile_and_noncanonical_headers(database):
    content = "Código;Marca;Modelo;Ano Fabricação\nA;BMW;F 900 R;2025\n".encode()
    service = PartnerInventoryImportService(database)
    preview = service.preview("thomas_motos", content, "stock.csv")
    assert preview["valid_rows"] == 1
    service.confirm(
        "thomas_motos",
        content,
        "C:/sensitive/stock.csv",
        reviewer="Teste",
        confirmed=True,
        authorized=True,
        motorcycles_confirmed=True,
    )
    state = read_operations(database)
    assert state["mappings"]["thomas_motos"]["manufacturer"] == "Marca"
    assert state["imports"][0]["filename"] == "stock.csv"


@pytest.mark.parametrize("flag", ["confirmed", "authorized", "motorcycles_confirmed"])
def test_confirmation_is_mandatory(database, flag):
    flags = dict(confirmed=True, authorized=True, motorcycles_confirmed=True)
    flags[flag] = False
    with pytest.raises(ValueError):
        PartnerInventoryImportService(database).confirm(
            "thomas_motos", file_bytes(), "stock.csv", reviewer="Teste", **flags
        )
    assert not read_operations(database)["imports"]


def test_partial_never_removes_and_full_snapshot_requires_complete_valid_file(database):
    confirm(database)
    confirm(database, data=[rows()[0]])
    assert len(DashboardService(DashboardConfig(database, "thomas_motos")).snapshot()["stock"]) == 2
    invalid = [rows()[0], {**rows()[1], "year": ""}]
    with pytest.raises(ValueError):
        confirm(database, data=invalid, mode="FULL_SNAPSHOT")
    assert len(DashboardService(DashboardConfig(database, "thomas_motos")).snapshot()["stock"]) == 2
    confirm(database, data=[rows()[0]], mode="FULL_SNAPSHOT")
    snapshot = DashboardService(DashboardConfig(database, "thomas_motos")).snapshot()
    assert len(snapshot["stock"]) == len(snapshot["queue"]) == 1


def test_duplicate_and_missing_identity_preview_is_explicit():
    preview = preview_file("moto_marques", file_bytes([rows()[0], rows()[0], {"manufacturer": "BMW"}]), "stock.csv")
    assert (
        preview["duplicates"] == 1 and preview["missing_id"] == preview["missing_year"] == preview["missing_model"] == 1
    )
    assert preview["invalid_rows"] == 2


def test_missing_id_is_scoped_to_exact_file_and_full_snapshot_rejected():
    data = [{k: v for k, v in rows()[0].items() if k != "external_id"}]
    content = file_bytes(data)
    one = preview_file("moto_marques", content, "one.csv")
    two = preview_file("moto_marques", content, "renamed.csv")
    assert one["rows"][0]["data"]["external_id"] == two["rows"][0]["data"]["external_id"]
    assert one["rows"][0]["generated_id"]
    assert preview_file("moto_marques", content, "a.csv", mode="FULL_SNAPSHOT")["invalid_rows"] == 1


@pytest.mark.parametrize("data", [b"", b"marca,marca\nBMW,BMW", b"manufacturer,model,year\nBMW,F900R,not-year"])
def test_invalid_files_never_publish(database, data):
    service = PartnerInventoryImportService(database)
    with pytest.raises(ValueError):
        service.confirm(
            "moto_marques",
            data,
            "stock.csv",
            reviewer="Teste",
            confirmed=True,
            authorized=True,
            motorcycles_confirmed=True,
        )
    assert not read_operations(database)["imports"]


def test_xlsx_formula_rejected():
    data = [{**rows()[0], "model": "=1+1"}]
    with pytest.raises(ValueError, match="fórmulas"):
        preview_file("thomas_motos", file_bytes(data, "xlsx"), "stock.xlsx")


def test_transaction_rolls_back_matching_failure(database, monkeypatch):
    monkeypatch.setattr(
        "services.partner_inventory_import.build_coverage", lambda *a: (_ for _ in ()).throw(ValueError("fixture"))
    )
    with pytest.raises(ValueError):
        confirm(database)
    state = read_operations(database)
    assert not state["imports"]
    with sqlite3.connect(database) as db:
        assert db.execute("select count(*) from partner_advertisements").fetchone()[0] == 0
    assert state["alerts"][0]["code"] == "IMPORT_FAILED"


def test_motonil_stage_human_memory_reclassification_and_identity_change(database):
    service = MotonilStagingService(database)
    service.stage([staged(), staged("2", "Kart")])
    assert not DashboardService(DashboardConfig(database, "motonil")).snapshot()["stock"]
    service.classify(
        "1", "MOTORCYCLE", reviewer="Teste", note="Conferido no anúncio", expected_revision=1, identity=rows()[0]
    )
    service.classify("2", "KART", reviewer="Teste", note="Kart confirmado", expected_revision=1)
    assert len(DashboardService(DashboardConfig(database, "motonil")).snapshot()["stock"]) == 1
    assert service.stage([staged(), staged("2", "Kart")])["accepted_from_memory"] == 1
    service.classify("1", "SERVICE", reviewer="Outro", note="Correção", expected_revision=2)
    assert not DashboardService(DashboardConfig(database, "motonil")).snapshot()["stock"]
    assert not DashboardService(DashboardConfig(database, "motonil")).snapshot()["queue"]
    service.classify("2", "MOTORCYCLE", reviewer="Teste", note="Nova revisão", expected_revision=2, identity=rows()[0])
    service.stage([staged("2", "Identidade alterada")])
    state = read_operations(database)
    assert next(r for r in state["staging"] if r["external_id"] == "2")["classification"] == "PENDING_CLASSIFICATION"
    assert not DashboardService(DashboardConfig(database, "motonil")).snapshot()["stock"]
    assert any(e["action"] == "TRIAGE_INVALIDATED" for e in state["events"])


def test_stale_revision_and_unknown_never_publish(database):
    service = MotonilStagingService(database)
    service.stage([staged()])
    service.classify("1", "UNKNOWN", reviewer="Teste", note="Insuficiente", expected_revision=1)
    with pytest.raises(ValueError, match="mudou"):
        service.classify("1", "MOTORCYCLE", reviewer="Teste", note="Conferido", expected_revision=1, identity=rows()[0])
    assert read_operations(database)["metrics"]["pending_triage"] == 1


def test_motonil_http_is_bounded_and_stages_only(database):
    calls = []

    def reader(url):
        calls.append(url)
        return (
            (404, "")
            if url.endswith("robots.txt")
            else (200, Path("tests/fixtures/partner_diagnostics/motonil_mixed.html").read_text(encoding="utf-8"))
        )

    report = MotonilStagingService(database).collect(reader=reader, sleeper=lambda _: None)
    assert report["staged"] == 3 and len(calls) == 2
    assert read_operations(database)["metrics"]["pending_triage"] == 3


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_auth_errors_redacted(status):
    with pytest.raises(SourceError) as error:
        FakeAuthenticatedSource(status=status).read()
    assert "fixture-only" not in str(error.value)
    assert error.value.code == ("AUTH_FAILED" if status in {401, 403} else "SOURCE_UNAVAILABLE")


def test_auth_missing_expired_timeout_empty_and_valid(database):
    assert FakeAuthenticatedSource(missing=True).read()["status"] == "AGUARDANDO_CONFIGURACAO"
    for source in [
        FakeAuthenticatedSource([]),
        FakeAuthenticatedSource(error=requests.Timeout("secret")),
        FakeAuthenticatedSource([{"Codigo": 1}]),
    ]:
        with pytest.raises(SourceError):
            source.read()
    source = FakeAuthenticatedSource(
        [{"Codigo": 1, "TipoVeiculo": "Moto", "Marca": "BMW", "Modelo": "F 900 R", "AnoModelo": 2025}]
    )
    assert collect_authenticated(database, source=source, confirmed=True, reviewer="Teste")["imported_rows"] == 1
    assert all("fixture-only" not in str(e) for e in read_operations(database)["events"])


def test_readonly_mutations_rejected_but_preview_available(database):
    service = PartnerInventoryImportService(database, read_only=True)
    assert service.preview("thomas_motos", file_bytes(), "stock.csv")["valid_rows"] == 2
    with pytest.raises(ValueError, match="leitura"):
        service.confirm(
            "thomas_motos",
            file_bytes(),
            "stock.csv",
            reviewer="Teste",
            confirmed=True,
            authorized=True,
            motorcycles_confirmed=True,
        )
    with pytest.raises(ValueError, match="leitura"):
        MotonilStagingService(database, read_only=True).stage([staged()])


def test_cli_dryrun_does_not_create_database(tmp_path, capsys):
    file = tmp_path / "sample.csv"
    file.write_bytes(file_bytes())
    absent = tmp_path / "absent.sqlite3"
    assert main(["import", "moto_marques", str(file), "--dry-run", "--db", str(absent)]) == 0
    assert json.loads(capsys.readouterr().out)["valid_rows"] == 2 and not absent.exists()
    assert main(["status", "--db", str(absent)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {p["integration_mode"] for p in data} == {"PUBLIC_COLLECTION", "FILE_IMPORT", "STAGED_COLLECTION"}


def test_alerts_metrics_and_assistant_are_read_only(database):
    service = MotonilStagingService(database)
    service.stage([staged()])
    service.stage([staged()])
    before = database.read_bytes()
    state = read_operations(database)
    assert state["metrics"]["operational"] == 4 and len(state["alerts"]) == 1
    assistant = AIAssistantService(database, config=AssistantConfig(enabled=True, provider="fake", audit_enabled=False))
    result = assistant.ask("Quantos itens aguardam triagem na Motonil?", new_conversation())
    assert result["success"] and any("aguardando triagem: 1" in f["text"] for f in result["facts"])
    assert database.read_bytes() == before


def test_operational_ui_no_network(database, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: pytest.fail("network"))
    app = AppTest.from_string(
        f"from pathlib import Path\nfrom services.dashboard_service import DashboardConfig,DashboardService\nfrom ui.partner_operations import operations_page\noperations_page(DashboardService(DashboardConfig(Path({str(database)!r}),read_only=True)))",
        default_timeout=30,
    ).run()
    assert not app.exception
    assert len(app.get("file_uploader")) == 2
    assert any("Triagem Motonil" == e.label for e in app.expander)
    assert any(b.label == "Coletar Motonil para triagem" and b.disabled for b in app.button)


def test_modes_and_scheduler_skip_manual_partners(database, monkeypatch):
    from services.partner_operation_scheduler import run_operation
    from services.scheduler_config import SchedulerConfig

    for key in ("thomas_motos", "motonil", "moto_marques"):
        assert integration(key).enabled
        assert run_operation(database, SchedulerConfig(), partner_key=key)["status"] == "DISABLED"
    monkeypatch.setenv("MOTONIL_AUTOMATION_ENABLED", "true")
    calls = []
    monkeypatch.setattr(MotonilStagingService, "collect", lambda self: calls.append("staging") or {"staged": 3})
    assert run_operation(database, SchedulerConfig(), partner_key="motonil")["status"] == "SUCCESS"
    assert calls == ["staging"]


def test_run_all_includes_only_explicit_automation_and_isolates_failure(database, monkeypatch):
    from services.multi_partner_service import run_all
    from services.scheduler_config import SchedulerConfig

    monkeypatch.setenv("MOTONIL_AUTOMATION_ENABLED", "true")
    monkeypatch.setattr(
        MotonilStagingService, "collect", lambda _: (_ for _ in ()).throw(ValueError("fixture failure"))
    )
    calls = []

    def runner(*args, **kwargs):
        calls.append(kwargs["partner_key"])
        return {"status": "SUCCESS"}

    report = run_all(database, SchedulerConfig(), runner=runner)
    assert set(report) == {"wr_motos", "motonil"} and calls == ["wr_motos"]
    assert report["wr_motos"]["status"] == "SUCCESS" and report["motonil"]["status"] == "FAILED"


def test_scheduler_tick_routes_to_staging_and_manual_import_is_disabled(database, tmp_path, monkeypatch):
    from dataclasses import asdict
    from datetime import datetime, timedelta, timezone

    from database.pipeline_repository import PipelineRepository, read_pipeline
    from services.partner_operation_scheduler import serve_operation
    from services.scheduler_config import SchedulerConfig

    config = SchedulerConfig(reports=str(tmp_path / "reports"), log_file=str(tmp_path / "scheduler.log"))
    path = tmp_path / "scheduler.json"
    path.write_text(json.dumps(asdict(config)), encoding="utf-8")
    now = datetime.now(timezone.utc)
    with PipelineRepository(database) as repo:
        repo.scheduler(config, now - timedelta(seconds=1), "STOPPED", "motonil")
    calls = []
    monkeypatch.setenv("MOTONIL_AUTOMATION_ENABLED", "true")
    monkeypatch.setattr(MotonilStagingService, "collect", lambda self: calls.append("motonil") or {"staged": 1})
    serve_operation(database, path, partner_key="motonil", clock=lambda: now, max_ticks=1)
    serve_operation(database, path, partner_key="moto_marques", clock=lambda: now, max_ticks=1)
    assert calls == ["motonil"]
    assert read_pipeline(database, partner="moto_marques")["scheduler"]["status"] == "DISABLED"


def test_four_origins_one_scanner_and_one_human_development_item(database):
    from test_development import create
    from test_review_queue import ad, coverage

    from services.development_service import DevelopmentService
    from services.partner_identity_service import stock_origins

    import_base(database, [motorcycle(status="SEM_SUPORTE")])
    coverage(database, [ad()], database.parent / "wr-report")
    for partner in ("thomas_motos", "moto_marques"):
        confirm(database, partner, data=[rows()[0]])
    service = MotonilStagingService(database)
    service.stage([staged()])
    service.classify(
        "1", "MOTORCYCLE", reviewer="Teste", note="Conferência da fixture", expected_revision=1, identity=rows()[0]
    )
    config = DashboardConfig(database)
    wr = DashboardService(config).snapshot()["stock"][0]
    assert len(stock_origins(config, wr)) == 4
    with sqlite3.connect(database) as db:
        assert db.execute("select count(*) from development_items").fetchone()[0] == 0
        assert db.execute("select count(*) from motorcycles").fetchone()[0] == 1
    identifiers = []
    for partner, identifier in [
        ("wr_motos", "1"),
        ("thomas_motos", "stock-1"),
        ("moto_marques", "stock-1"),
        ("motonil", "1"),
    ]:
        identifiers.append(create(DevelopmentService(DashboardConfig(database, partner)), identifier))
    assert len(set(identifiers)) == 1


def test_authenticated_source_requires_explicit_audit_before_scheduling(monkeypatch):
    monkeypatch.setenv("THOMAS_API_TOKEN", "fixture-only")
    monkeypatch.setenv("THOMAS_AUTHORIZED", "true")
    monkeypatch.setenv("THOMAS_MOTORCYCLE_TYPE", "Moto")
    monkeypatch.setenv("THOMAS_AUTOMATION_ENABLED", "true")
    monkeypatch.delenv("THOMAS_AUTH_VALIDATED", raising=False)
    assert integration("thomas_motos").integration_mode == "AUTHENTICATED_COLLECTION"
    assert not integration("thomas_motos").automation_enabled
    monkeypatch.setenv("THOMAS_AUTH_VALIDATED", "true")
    assert integration("thomas_motos").automation_enabled


def test_real_token_transport_uses_fixed_endpoint_and_never_follows_redirects(monkeypatch):
    from partners.authenticated_source import ENDPOINT, AuthenticatedSource

    calls = []

    class Response:
        status_code = 302

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(requests, "get", get)
    source = AuthenticatedSource(
        environ={"THOMAS_API_TOKEN": "fixture-token", "THOMAS_AUTHORIZED": "true", "THOMAS_MOTORCYCLE_TYPE": "Moto"}
    )
    with pytest.raises(SourceError) as error:
        source.read()
    assert calls[0][0] == ENDPOINT and calls[0][1]["allow_redirects"] is False
    assert calls[0][1]["timeout"] == 20 and "fixture-token" not in str(error.value)


def test_dashboard_can_select_imported_partner_and_open_review(database, monkeypatch):
    confirm(database, data=[rows()[0]])
    monkeypatch.setenv("MOTO_DB", str(database))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    app = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    assert not app.exception
    assert "Thomas Motos" in app.sidebar.selectbox[0].options
    app.sidebar.selectbox[0].set_value("thomas_motos").run()
    for page in [
        "Fila de revisão",
        "Possíveis novas motos",
        "Indicadores gerenciais",
        "Parceiros",
        "Alertas",
        "Assistente de IA",
    ]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page


def test_manual_partner_can_use_existing_priority_engine(database):
    from services.prioritization_service import PrioritizationService

    confirm(database, data=[rows()[1]])
    service = PrioritizationService(DashboardConfig(database, "thomas_motos"))
    result = service.refresh("collection")
    assert result["evaluated"] > 0
    with sqlite3.connect(database) as db:
        assert (
            db.execute("SELECT count(*) FROM priority_cases WHERE partner='thomas_motos' AND active=1").fetchone()[0]
            > 0
        )


def test_run_all_stages_motonil_even_when_public_registry_is_disabled(database, monkeypatch):
    from types import SimpleNamespace

    from services import multi_partner_service, partner_operation_scheduler
    from services.scheduler_config import load_config

    monkeypatch.setenv("MOTONIL_AUTOMATION_ENABLED", "true")
    monkeypatch.setattr(multi_partner_service, "PartnerRegistry", lambda: SimpleNamespace(list=lambda **kw: []))
    calls = []

    def run(database, config, *, partner_key):
        calls.append(partner_key)
        return {"status": "SUCCESS"}

    monkeypatch.setattr(partner_operation_scheduler, "run_operation", run)
    result = multi_partner_service.run_all(database, load_config())
    assert calls == ["motonil"]
    assert result == {"motonil": {"status": "SUCCESS"}}
