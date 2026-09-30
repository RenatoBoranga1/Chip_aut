import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile

import pytest
from streamlit.testing.v1 import AppTest
from test_review_queue import ad, coverage
from test_scanner import row, workbook_file

from app.scanner_base import main
from database.repository import SQLiteRepository
from database.review_repository import ReviewRepository
from database.scanner_repository import active_import
from services.import_service import import_base
from services.scanner_service import ScannerService
from services.scanner_validation import config, validate_upload


def content(tmp_path, rows=None, name="input.xlsx"):
    return workbook_file(tmp_path / name, rows or [row()]).read_bytes()


@pytest.fixture
def service(tmp_path):
    db = tmp_path / "db.sqlite3"
    f = workbook_file(tmp_path / "original.xlsx", [row(), row(D="R 1200 GS")])
    import_base(f, db)
    return ScannerService(db)


def prepare(s, tmp_path, rows=None):
    return s.prepare(
        content(tmp_path, rows or [row(A="Não", I=""), row(D="NEW 1000")]), "new.xlsx", "Pessoa", "Ensaio"
    )["id"]


def publish(s, v):
    d = s.detail(v)
    return s.publish(v, "Pessoa", "Revisado", True, d["parent_import_id"], d["impact_token"])


def active(s):
    with sqlite3.connect(s.database) as c:
        return active_import(c)


def test_staging_comparison_publication(service, tmp_path):
    original = (tmp_path / "original.xlsx").read_bytes()
    v = prepare(service, tmp_path)
    assert active(service) == 1
    d = service.detail(v)
    c = d["report"]["comparison"]
    assert (c["added"], c["removed"], c["changed"], c["unchanged"]) == (1, 1, 1, 0)
    assert c["identity_review"] == 1
    result = publish(service, v)
    assert result["derived"] == "DONE" and active(service) == 2
    assert service.detail(v)["status"] == "PUBLISHED"
    assert sum(r["status"] == "PUBLISHED" for r in service.list()["versions"]) == 1
    assert (tmp_path / "original.xlsx").read_bytes() == original
    with SQLiteRepository(service.database) as repo:
        assert repo.connection.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert not repo.connection.execute("pragma foreign_key_check").fetchall()
        assert repo.connection.execute("select count(*) from motorcycle_snapshots where import_id=1").fetchone()[0] == 2


@pytest.mark.parametrize(
    "name,data", [("bad.xls", b"x"), ("bad.xlsx", b"x"), ("bad.xlsx", b"PK\x03\x04garbage"), ("empty.xlsx", b"")]
)
def test_invalid_file(tmp_path, name, data):
    with pytest.raises(ValueError):
        validate_upload(data, name)


def test_limits_macros_and_integrity(tmp_path):
    data = content(tmp_path)
    with pytest.raises(ValueError):
        validate_upload(data, "a.xlsx", config() | {"max_upload_mb": 0.0001})
    f = tmp_path / "input.xlsx"
    with ZipFile(f, "a") as z:
        z.writestr("xl/vbaProject.bin", b"not executable")
    with pytest.raises(ValueError, match="Macros"):
        validate_upload(f.read_bytes(), "a.xlsx")


@pytest.mark.parametrize(
    "change", [{"C": ""}, {"D": ""}, {"E": "2024/2025"}, {"F": ""}, {"B": "invalid-date"}, {"D": "=1+1"}]
)
def test_rejected_rows_block_publication(service, tmp_path, change):
    v = prepare(service, tmp_path, [row(), row(**change)])
    assert service.detail(v)["status"] == "REJECTED"
    with pytest.raises(ValueError):
        publish(service, v)
    assert active(service) == 1


def test_duplicate_hash_and_path_traversal(service, tmp_path):
    data = content(tmp_path, [row(D="NEW")])
    first = service.prepare(data, "../../escape.xlsx", "Pessoa")
    second = service.prepare(data, "renamed.xlsx", "Pessoa")
    assert second == {"id": first["id"], "duplicate": True}
    assert service.detail(first["id"])["original_filename"] == "escape.xlsx"
    assert service.detail(first["id"])["sha256"] == hashlib.sha256(data).hexdigest()
    assert not (tmp_path.parent / "escape.xlsx").exists()
    publish(service, first["id"])
    with pytest.raises(ValueError):
        publish(service, first["id"])
    assert active(service) == 2


def test_unchanged_and_normalized_nomenclature(service, tmp_path):
    v = prepare(service, tmp_path, [row(D="F900 R"), row(D="R 1200 GS")])
    c = service.detail(v)["report"]["comparison"]
    assert c["added"] == c["removed"] == 0 and c["changed"] == 1 and c["unchanged"] == 1


def test_unknown_support_and_conflicts(service, tmp_path):
    v = prepare(service, tmp_path, [row(A="V16", I=""), row(A="Não", I="")])
    d = service.detail(v)
    assert d["report"]["conflicts"] == 1
    publish(service, v)
    from database.matching_repository import MatchingRepository

    with MatchingRepository(service.database) as repo:
        assert repo.matching_snapshot()[2][0].status == "SEM_STATUS"


@pytest.mark.parametrize(
    "confirmed,author,note", [(False, "Pessoa", "motivo"), (True, "", "motivo"), (True, "Pessoa", "")]
)
def test_confirmation(service, tmp_path, confirmed, author, note):
    v = prepare(service, tmp_path)
    d = service.detail(v)
    with pytest.raises(ValueError):
        service.publish(v, author, note, confirmed, d["parent_import_id"], d["impact_token"])
    assert active(service) == 1


def test_concurrent_publish_and_stale_compare(service, tmp_path):
    v = prepare(service, tmp_path)
    w = prepare(service, tmp_path, [row(D="Another")])

    def attempt(i):
        try:
            return publish(service, i)["import_id"]
        except ValueError:
            return "stale"

    with ThreadPoolExecutor(2) as pool:
        out = list(pool.map(attempt, [v, w]))
    assert sorted(map(str, out)) == ["2", "stale"]
    loser = v if out[0] == "stale" else w
    service.compare(loser, "Pessoa")
    publish(service, loser)
    assert active(service) == 3


def test_atomic_rollback(service, tmp_path, monkeypatch):
    v = prepare(service, tmp_path)

    def fail(*args):
        raise RuntimeError("injected")

    monkeypatch.setattr(service, "_alerts", fail)
    with pytest.raises(RuntimeError):
        publish(service, v)
    assert active(service) == 1 and service.detail(v)["status"] == "VALIDATED"
    with sqlite3.connect(service.database) as c:
        assert c.execute("select count(*) from scanner_jobs").fetchone()[0] == 0
        assert c.execute("select count(*) from scanner_alerts where alert_type='SCANNER_FAILED'").fetchone()[0] == 1


def test_tampered_staging(service, tmp_path):
    v = prepare(service, tmp_path)
    with sqlite3.connect(service.database) as c:
        c.execute("update scanner_versions set content=? where id=?", (b"bad", v))
    with pytest.raises(ValueError):
        publish(service, v)
    assert active(service) == 1


def test_recovery_dedup_and_history(service, tmp_path, monkeypatch):
    v = prepare(service, tmp_path)
    import services.scanner_refresh as module

    real = module.refresh_operational
    monkeypatch.setattr(module, "refresh_operational", lambda *a: (_ for _ in ()).throw(RuntimeError("transient")))
    assert publish(service, v)["derived"] == "PENDING" and active(service) == 2
    monkeypatch.setattr(module, "refresh_operational", real)
    assert service.resume(v) == "DONE" and service.resume(v) == "DONE"
    from database.scanner_alert_repository import history, read_scanner_alerts, transition

    alerts = read_scanner_alerts(service.database, "wr_motos")
    assert len(alerts) == 1
    transition(service.database, alerts[0]["id"], "LIDO", "wr_motos")
    assert len(history(service.database, alerts[0]["id"], "wr_motos")) == 1
    with sqlite3.connect(service.database) as c:
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE scanner_events SET actor='x'")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("DELETE FROM scanner_versions WHERE id=?", (v,))


def test_human_revalidation_no_new_collection(service, tmp_path):
    coverage(service.database, [ad(model="MISSING 900")], tmp_path / "coverage")
    with ReviewRepository(service.database) as repo:
        item = repo.connection.execute("select id from review_items limit 1").fetchone()[0]
        repo.decide(item, "NAO_EXISTE_NA_BASE", "Pessoa", "Conferido", None)
        count = repo.connection.execute("select count(*) from partner_collections").fetchone()[0]
    v = prepare(service, tmp_path, [row(D="MISSING 900")])
    assert service.detail(v)["report"]["review_affected"] == 1
    publish(service, v)
    with ReviewRepository(service.database) as repo:
        result = repo.show(item)
        assert result["state"] == "invalidated"
        assert result["memory"]["stale_reason"] == "STALE_BASE_VERSION"
        assert repo.connection.execute("select count(*) from review_decisions").fetchone()[0] == 1
        assert repo.connection.execute("select count(*) from partner_collections").fetchone()[0] == count


def test_present_confirmation_remains_and_manual_priority(service, tmp_path):
    coverage(service.database, [ad(model="F900")], tmp_path / "coverage")
    with ReviewRepository(service.database) as repo:
        item = repo.connection.execute("select id from review_items limit 1").fetchone()[0]
        repo.decide(item, "CONFIRMAR_MATCH", "Pessoa", "Conferido", "BMW|F900R|2025")
    from services.dashboard_service import DashboardConfig
    from services.prioritization_service import PrioritizationService

    pr = PrioritizationService(DashboardConfig(service.database))
    pr.refresh()
    r = pr.listing()["items"][0]
    pr.override(r["id"], "high", author="Pessoa", reason="Manual", request_key="once", revision=r["revision"])
    v = prepare(service, tmp_path, [row(A="Não", I="")])
    publish(service, v)
    with ReviewRepository(service.database) as repo:
        assert repo.show(item)["memory"]["valid"]
    assert pr.detail(r["id"])["effective_priority"] == "high"
    assert pr.detail(r["id"])["scanner_base_version"] == 2


def test_preview_cli_read_only_and_dashboard(service, tmp_path, monkeypatch):
    v = prepare(service, tmp_path)
    ro = ScannerService(service.database, True)
    with pytest.raises(ValueError):
        ro.prepare(content(tmp_path), "new.xlsx", "Pessoa")
    with sqlite3.connect(service.database) as c:
        before = "\n".join(c.iterdump())
    assert main(["validate", str(tmp_path / "input.xlsx"), "--db", str(service.database)]) == 0
    assert main(["list", "--db", str(service.database)]) == 0
    monkeypatch.setenv("MOTO_DB", str(service.database))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    app = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Atualização da base do scanner").run()
    next(s for s in app.selectbox if s.label == "Consultar versão").set_value(v).run()
    assert not app.exception and not app.error
    assert next(b for b in app.button if b.label == "Confirmar publicação").disabled
    with sqlite3.connect(service.database) as c:
        assert "\n".join(c.iterdump()) == before
    assert 'initial_sidebar_state="expanded"' in Path("app/dashboard.py").read_text(encoding="utf-8")
    assert "[data-testid='stToolbar']" not in Path("app/dashboard.py").read_text(encoding="utf-8")


def test_migration_from_previous_and_pagination(service, tmp_path):
    for i in range(4):
        prepare(service, tmp_path, [row(D=f"NEW {i}")])
    assert len(service.list()["versions"]) == 5
    assert service.list(1)["versions"] == []
    assert service.detail(2, page=100)["differences"] == []
    with sqlite3.connect(service.database) as c:
        assert c.execute("select max(version) from schema_version").fetchone()[0] == 14


@pytest.mark.parametrize(
    "bad",
    [
        {"version": 2},
        {"auto_publish": True},
        {"max_upload_mb": -1},
        {"max_upload_mb": True},
        {"enabled": "yes"},
        {"require_confirmation": False},
    ],
)
def test_config_protections(tmp_path, monkeypatch, bad):
    data = config() | bad
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("MOTO_SCANNER_IMPORT_CONFIG", str(p))
    with pytest.raises(ValueError):
        config()


def test_no_macro_disguised_or_traversal(tmp_path):
    data = content(tmp_path)
    import io

    for member in ["../escape.xml", "xl/externalLinks/link.xml"]:
        out = io.BytesIO(data)
        with ZipFile(out, "a") as z:
            z.writestr(member, b"test")
        with pytest.raises(ValueError):
            validate_upload(out.getvalue(), "file.xlsx")


def test_stale_decision_token(service, tmp_path):
    v = prepare(service, tmp_path)
    coverage(service.database, [ad(model="MISSING")], tmp_path / "coverage")
    with ReviewRepository(service.database) as repo:
        item = repo.connection.execute("select id from review_items limit 1").fetchone()[0]
        repo.decide(item, "DEIXAR_PENDENTE", "Pessoa", "Conferir", None)
    with pytest.raises(ValueError, match="decisões"):
        publish(service, v)
    service.compare(v, "Pessoa")
    assert publish(service, v)["derived"] == "DONE"


def test_development_notice_without_mutation(service, tmp_path):
    from database.scanner_alert_repository import development_notice
    from services.dashboard_service import DashboardConfig, DashboardService
    from services.development_service import DevelopmentService

    coverage(service.database, [ad(model="MISSING 900")], tmp_path / "coverage")
    dashboard = DashboardService(DashboardConfig(service.database))
    item = dashboard.snapshot()["queue"][0]
    with ReviewRepository(service.database) as repo:
        repo.decide(item["id"], "NAO_EXISTE_NA_BASE", "Pessoa", "Conferido", None)
    dev = DevelopmentService(dashboard.config)
    # Follow the same explicit development command used by the existing workflow.
    task = dev.create(
        "review",
        item["id"],
        reason="CONFIRMED_MISSING",
        actor="Pessoa",
        justification="Confirmada",
        confirmed=True,
        command_key="dev-scanner",
    )
    task_id = task["id"] if isinstance(task, dict) else task
    before = dev.detail(task_id)
    v = prepare(service, tmp_path, [row(D="MISSING 900")])
    assert service.detail(v)["report"]["development_affected"] == 1
    publish(service, v)
    after = dev.detail(task_id)
    for field in ["status", "assigned_to", "priority", "checklist", "revision"]:
        assert before[field] == after[field]
    assert development_notice(service.database, task_id) == v


def test_scheduler_retry_and_latest_version_only(service, tmp_path, monkeypatch):
    import services.scanner_refresh as mod

    v = prepare(service, tmp_path)
    real = mod.refresh_operational
    monkeypatch.setattr(mod, "refresh_operational", lambda *a: (_ for _ in ()).throw(RuntimeError("retry")))
    publish(service, v)
    monkeypatch.setattr(mod, "refresh_operational", real)
    mod.safe_resume(service.database)
    assert service.detail(v)["job"]["status"] == "DONE"
    assert "safe_resume(database)" in Path("services/scheduler_service.py").read_text(encoding="utf-8")


def test_sparse_dimension_and_mandatory_headers(tmp_path):
    import io

    data = content(tmp_path)
    out = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as src, ZipFile(out, "w") as dst:
        for item in src.infolist():
            payload = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                payload = payload.replace(b'ref="A1:I2"', b'ref="A1:XFD1048576"')
            dst.writestr(item, payload)
    assert validate_upload(out.getvalue(), "sparse.xlsx")[2]["valid_records"] == 1
    out = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as src, ZipFile(out, "w") as dst:
        for item in src.infolist():
            payload = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                payload = payload.replace(b"MONTADORA", b"INVALID")
            dst.writestr(item, payload)
    with pytest.raises(ValueError):
        validate_upload(out.getvalue(), "bad.xlsx")


def test_prepared_selection_survives_form_submission(service, tmp_path, monkeypatch):
    v = prepare(service, tmp_path)
    monkeypatch.setenv("MOTO_DB", str(service.database))
    monkeypatch.setenv("MOTO_READ_ONLY", "0")
    app = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    app.session_state["scanner_selection"] = v
    app.sidebar.radio[0].set_value("Atualização da base do scanner").run()
    next(b for b in app.button if b.label == "Confirmar publicação").click().run()
    assert any("Confirmação explícita" in e.value for e in app.error)
    assert app.selectbox(key="scanner_version_choice").value == v
    assert active(service) == 1


def test_legacy_cli_cannot_bypass_confirmation(service, tmp_path, monkeypatch):
    import sys

    from app.import_base import main as legacy_main

    monkeypatch.setattr(sys, "argv", ["import_base", str(tmp_path / "original.xlsx"), "--db", str(service.database)])
    with pytest.raises(SystemExit) as exc:
        legacy_main()
    assert exc.value.code == 2
    assert active(service) == 1
