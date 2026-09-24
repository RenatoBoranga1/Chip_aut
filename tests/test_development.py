import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from test_matching import motorcycle
from test_review_queue import ad, coverage, import_base

from database.development_repository import DevelopmentRepository
from database.repository import SQLiteRepository
from database.review_repository import ReviewRepository
from services.alert_service import AlertService
from services.dashboard_service import DashboardConfig, DashboardService
from services.development_alerts import scan_stale
from services.development_policy import TRANSITIONS, load_development_config
from services.development_service import DevelopmentService


@pytest.fixture
def dev(tmp_path):
    path = tmp_path / "db.sqlite3"
    import_base(path, [motorcycle("F 900 R", status="SEM_SUPORTE")])
    coverage(path, [ad(), ad(external_id="2", model="NOVA 900")], tmp_path / "reports")
    return DevelopmentService(DashboardConfig(path))


def create(dev, identifier="1", **kwargs):
    values = {
        "actor": "Operador de teste",
        "justification": "Necessidade avaliada em fixture",
        "reason": "MANUAL",
        "confirmed": True,
        "command_key": str(uuid4()),
    }
    return dev.create("advertisement", identifier, **(values | kwargs))


def change(dev, item, action, value, **kwargs):
    params = {
        "actor": "Operador de teste",
        "justification": "Alteração avaliada",
        "command_key": str(uuid4()),
        "expected_revision": dev.detail(item)["revision"],
    }
    return dev.change(item, action, value, **(params | kwargs))


def operational_dump(path):
    with sqlite3.connect(path) as db:
        return [
            line
            for line in db.iterdump()
            if line.startswith("INSERT INTO") and not line.startswith('INSERT INTO "development_')
        ]


def test_create_explicit_and_separate_from_coverage(dev):
    before = operational_dump(dev.config.database)
    item = create(dev, reason="UNSUPPORTED", priority="high")
    detail = dev.detail(item)
    assert detail["status"] == "NEW" and detail["current_scanner"]["status"] == "SEM_SUPORTE"
    assert detail["created_by"] == "Operador de teste" and len(detail["origins"]) == 1
    assert len(detail["checklist"]) == 8
    assert detail["history"][-1]["action"] == "CREATE"
    assert operational_dump(dev.config.database) == before
    assert AlertService(dev.config).snapshot()["alerts"][0]["alert_type"] == "DEV_NEW"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"confirmed": False},
        {"actor": ""},
        {"justification": " "},
        {"priority": "urgent"},
        {"reason": "CONFIRMED_MISSING"},
        {"reason": "INVALID"},
    ],
)
def test_creation_rejects_invalid_or_unsupported_claims(dev, kwargs):
    with pytest.raises(ValueError):
        create(dev, **kwargs)
    assert dev.listing()["total"] == 0


def test_unmatched_does_not_claim_unsupported(dev):
    with pytest.raises(ValueError):
        create(dev, "2", reason="UNSUPPORTED")
    item = create(dev, "2", reason="NEW_MODEL")
    detail = dev.detail(item)
    assert not detail["absence_confirmed_current"] and detail["current_scanner"] is None


def test_confirmed_absence_expires_and_reconciles_without_closing(dev):
    rid = next(r["id"] for r in DashboardService(dev.config).snapshot()["queue"] if r["external_id"] == "2")
    with ReviewRepository(dev.config.database) as repo:
        repo.decide(rid, "NAO_EXISTE_NA_BASE", "Teste", "Ausência conferida", None)
    item = create(dev, "2", reason="CONFIRMED_MISSING")
    assert dev.detail(item)["absence_confirmed_current"]
    import_base(dev.config.database, [motorcycle("NOVA 900", status="SUPORTADO")])
    detail = dev.detail(item)
    assert not detail["absence_confirmed_current"] and detail["may_be_addressed"]
    assert detail["status"] == "NEW" and detail["reconciliation_candidate"]["status"] == "SUPORTADO"
    assert detail["current_scanner"] is None


def test_readonly_and_disabled_enforced(dev):
    readonly = DevelopmentService(replace(dev.config, read_only=True))
    with pytest.raises(ValueError, match="somente leitura"):
        create(readonly)
    disabled = DevelopmentService(dev.config, policy=dev.policy | {"enabled": False})
    with pytest.raises(ValueError, match="desabilitada"):
        create(disabled)


def test_dedup_and_command_idempotence(dev):
    item = create(dev, command_key="same")
    assert create(dev, command_key="same") == item
    assert create(dev) == item
    detail = dev.detail(item)
    assert dev.listing()["total"] == 1 and detail["origins"][0]["occurrence_count"] == 1
    with pytest.raises(ValueError, match="outros dados"):
        create(dev, command_key="same", justification="Changed payload")


def test_concurrent_creation(dev):
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: create(dev), range(4)))
    assert len(set(ids)) == 1
    assert dev.listing()["total"] == 1


def test_multi_partner_same_strict_identity(dev, tmp_path):
    first = create(dev, "2")
    coverage(dev.config.database, [ad(partner="outro", external_id="77", model="NOVA 900")], tmp_path / "other")
    other = DevelopmentService(replace(dev.config, partner="outro"))
    assert create(other, "77") == first
    assert len(dev.detail(first)["origins"]) == 2
    assert dev.listing(filters={"partner": ["outro"]})["total"] == 1
    coverage(
        dev.config.database, [ad(partner="outro", external_id="88", model="NOVA 900", version="GT")], tmp_path / "gt"
    )
    assert create(other, "88") != first


@pytest.mark.parametrize("state,targets", list(TRANSITIONS.items()))
def test_valid_transitions(dev, state, targets):
    item = create(dev)
    # Arrange each predecessor directly; commands remain the behavior under test.
    for target in targets:
        with sqlite3.connect(dev.config.database) as db:
            db.execute("UPDATE development_items SET status=?,assigned_to=? WHERE id=?", (state, "Teste", item))
        change(dev, item, "status", target, completion_version="fixture-v1")
        detail = dev.detail(item)
        assert detail["status"] == target
        assert detail["history"][0]["before"]["status"] == state
        assert detail["history"][0]["after"]["status"] == target
        assert bool(detail["completed_at"]) == (target == "COMPLETED")
        assert bool(detail["discarded_at"]) == (target == "DISCARDED")


@pytest.mark.parametrize("target", ["COMPLETED", "IN_VALIDATION", "IN_DEVELOPMENT", "NEW", "INVALID"])
def test_invalid_transitions_rollback(dev, target):
    item = create(dev)
    before = dev.detail(item)
    with pytest.raises(ValueError, match="Transição"):
        change(dev, item, "status", target)
    assert dev.detail(item) == before


def test_full_lifecycle_and_audit(dev):
    item = create(dev)
    change(dev, item, "assigned_to", "Renato")
    change(dev, item, "priority", "low")
    change(dev, item, "note", "Observação original")
    change(dev, item, "note", "Outra observação")
    change(dev, item, "checklist", {"identity": True, "tested": True})
    change(dev, item, "technical", {"ecu": "Teste ECU", "collected_on": "2026-09-24"})
    for target in [
        "UNDER_ANALYSIS",
        "WAITING_INFORMATION",
        "DATA_COLLECTED",
        "IN_DEVELOPMENT",
        "IN_VALIDATION",
        "COMPLETED",
    ]:
        change(dev, item, "status", target, completion_version="V-teste")
    item_data = dev.detail(item)
    assert item_data["completion_version"] == "V-teste" and item_data["assigned_to"] == "Renato"
    assert item_data["checklist"]["tested"]["done"] and item_data["technical"]["ecu"] == "Teste ECU"
    assert [e["after"]["text"] for e in item_data["history"] if e["action"] == "note"] == [
        "Outra observação",
        "Observação original",
    ]
    assert {"DEV_VALIDATION", "DEV_COMPLETED"} <= {
        a["alert_type"] for a in AlertService(dev.config).snapshot()["alerts"]
    }
    change(dev, item, "status", "UNDER_ANALYSIS")
    assert dev.detail(item)["completed_at"] is None
    change(dev, item, "status", "DISCARDED")
    assert dev.detail(item)["discarded_at"]


def test_completion_requires_assignee(dev):
    item = create(dev)
    with sqlite3.connect(dev.config.database) as db:
        db.execute("UPDATE development_items SET status='IN_VALIDATION' WHERE id=?", (item,))
    with pytest.raises(ValueError, match="responsável"):
        change(dev, item, "status", "COMPLETED")


def test_reopen_does_not_duplicate_active_identity(dev):
    first = create(dev)
    change(dev, first, "status", "DISCARDED")
    second = create(dev)
    with pytest.raises(ValueError, match="outro item ativo"):
        change(dev, first, "status", "UNDER_ANALYSIS")
    assert dev.detail(first)["status"] == "DISCARDED" and second != first


def test_optimistic_revision_and_mutation_retry(dev):
    item = create(dev)
    revision = dev.detail(item)["revision"]
    change(dev, item, "priority", "low", command_key="mutation", expected_revision=revision)
    assert change(dev, item, "priority", "low", command_key="mutation", expected_revision=revision) == item
    with pytest.raises(ValueError, match="outra operação"):
        change(dev, item, "assigned_to", "Outro", expected_revision=revision)


@pytest.mark.parametrize(
    "action,value",
    [
        ("technical", {"bad": "x"}),
        ("technical", {"collected_on": "24/09/2026"}),
        ("checklist", {"missing": True}),
        ("checklist", {"tested": "yes"}),
        ("note", ""),
        ("priority", "urgent"),
    ],
)
def test_invalid_edits(dev, action, value):
    item = create(dev)
    with pytest.raises(ValueError):
        change(dev, item, action, value)


def test_transaction_failure_rolls_back_item_and_alert(dev, monkeypatch):
    monkeypatch.setattr(DevelopmentRepository, "origin", lambda *a: (_ for _ in ()).throw(RuntimeError("fixture")))
    with pytest.raises(RuntimeError):
        create(dev, priority="high")
    assert dev.listing()["total"] == 0
    assert not AlertService(dev.config).snapshot()["alerts"]


def test_immutable_history_and_migration_integrity(dev):
    item = create(dev)
    with sqlite3.connect(dev.config.database) as db:
        for table in ["development_events", "development_occurrences", "development_alert_history"]:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(f"DELETE FROM {table}")
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    with SQLiteRepository(dev.config.database) as repo:
        assert repo.connection.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 11
    assert dev.detail(item)


def test_sla_uses_status_age_not_notes_and_deduplicates(dev):
    clock = [datetime(2026, 9, 24, tzinfo=timezone.utc)]
    dev.clock = lambda: clock[0]
    item = create(dev)
    change(dev, item, "status", "UNDER_ANALYSIS")
    change(dev, item, "status", "WAITING_INFORMATION")
    clock[0] += timedelta(days=7)
    assert not dev.detail(item)["attention"]
    clock[0] += timedelta(days=1)
    change(dev, item, "note", "Contato realizado")
    assert dev.detail(item)["attention"] and dev.detail(item)["days_in_status"] == 8
    assert scan_stale(dev.config.database, dev.policy, clock=dev.clock, force=True) == 1
    assert scan_stale(dev.config.database, dev.policy, clock=dev.clock, force=True) == 0
    change(dev, item, "status", "UNDER_ANALYSIS")
    assert not dev.detail(item)["attention"]


def test_development_alerts_use_existing_center_and_partner_guard(dev):
    create(dev, priority="high")
    service = AlertService(dev.config)
    alert = service.snapshot()["alerts"][0]
    assert alert["id"] < 0 and alert["pipeline_run_id"] is None
    service.transition(alert["id"], "LIDO")
    assert service.history(alert["id"])[-1]["after_status"] == "LIDO"
    other = AlertService(replace(dev.config, partner="other"))
    assert not other.snapshot()["alerts"]
    with pytest.raises(ValueError):
        other.transition(alert["id"], "RESOLVIDO")


def test_filters_metrics_pagination_and_bounded_histories(dev):
    first = create(dev, priority="low", assigned_to="Renato")
    second = create(dev, "2", priority="high")
    assert dev.listing()["metrics"]["active"] == 2
    assert dev.listing()["items"][0]["id"] == second
    assert dev.listing(filters={"assigned_to": ["Renato"]})["items"][0]["id"] == first
    assert dev.listing(filters={"reason": ["UNSUPPORTED"]})["total"] == 0
    assert dev.listing(filters={"photo": ["without"]})["total"] == 2
    assert dev.listing(text="NOVA")["total"] == 1
    assert len(dev.listing(size=1, page=1)["items"]) == 1
    assert "source" not in dev.listing()["items"][0]
    for n in range(35):
        change(dev, first, "note", str(n))
    assert len(dev.detail(first)["history"]) == 30
    assert dev.detail(first, 1)["history"]


def test_config_controlled_people_and_custom_checklist(dev):
    service = DevelopmentService(
        dev.config, policy=dev.policy | {"assignees": ["Renato"], "checklist": {"custom": "Conferência especial"}}
    )
    item = create(service, assigned_to="Renato")
    assert list(service.detail(item)["checklist"]) == ["custom"]
    with pytest.raises(ValueError, match="fora da lista"):
        change(service, item, "assigned_to", "Outro")


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", "yes"),
        ("stale_days", {"NEW": 0}),
        ("stale_days", {"COMPLETED": 3}),
        ("assignees", [7]),
        ("checklist", {"x": False}),
    ],
)
def test_config_rejects_invalid(tmp_path, field, value):
    path = tmp_path / "config.json"
    config = load_development_config()
    path.write_text(json.dumps(config | {field: value}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_development_config(path)


def test_cli_create_list_show_assign_and_status(dev):
    def cli(*args):
        return subprocess.run(
            [sys.executable, "-m", "app.development", "--db", str(dev.config.database), "--json", *args],
            capture_output=True,
            text=True,
        )

    result = cli(
        "create",
        "--source",
        "advertisement",
        "--id",
        "2",
        "--reason",
        "manual",
        "--confirm",
        "--actor",
        "Teste",
        "--justification",
        "Avaliado",
    )
    assert result.returncode == 0, result.stderr
    item = json.loads(result.stdout)["item"]
    assert json.loads(cli("list").stdout)["total"] == 1
    assert json.loads(cli("show", str(item)).stdout)["status"] == "NEW"
    for command, val, revision in [("assign", "Renato", 1), ("status", "under_analysis", 2)]:
        result = cli(
            command,
            str(item),
            "--to",
            val,
            "--actor",
            "Teste",
            "--justification",
            "Avaliado",
            "--revision",
            str(revision),
        )
        assert result.returncode == 0, result.stderr


def test_dashboard_page_and_actions_are_readonly_safe(dev, monkeypatch):
    from streamlit.testing.v1 import AppTest

    item = create(dev, "2")
    monkeypatch.setenv("MOTO_DB", str(dev.config.database))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    with sqlite3.connect(dev.config.database) as db:
        before = list(db.iterdump())
    ui = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    ui.radio(key="navigation").set_value("Motos para desenvolvimento").run()
    ui.selectbox(key="development_selection").set_value(item).run()
    assert not ui.exception and not ui.error
    assert any(b.label == "Registrar alteração" and b.disabled for b in ui.button)
    assert any("Possível ausência" in msg.value for msg in ui.info)
    with sqlite3.connect(dev.config.database) as db:
        assert list(db.iterdump()) == before


def test_new_database_without_migration_read_does_not_write(tmp_path):
    path = tmp_path / "old.sqlite3"
    # A real v10-shaped database, upgraded only by explicit write entry points.
    with sqlite3.connect(path) as db:
        for migration in sorted(Path("database/migrations").glob("*.sql")):
            if migration.name.startswith("011"):
                break
            db.executescript(migration.read_text(encoding="utf-8"))
            db.execute("INSERT OR IGNORE INTO schema_version VALUES (?)", (int(migration.name[:3]),))
    service = DevelopmentService(DashboardConfig(path, read_only=True))
    assert not service.listing()["installed"]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 10
    with SQLiteRepository(path) as repo:
        assert repo.connection.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 11


def test_create_from_review_alert_and_scanner_share_identity(dev, tmp_path):
    from test_pipeline import result, run

    from services.scheduler_config import SchedulerConfig

    rid = next(r["id"] for r in DashboardService(dev.config).snapshot()["queue"] if r["external_id"] == "1")
    args = {"actor": "Teste", "justification": "Conferido", "reason": "UNSUPPORTED", "confirmed": True}
    item = dev.create("review", rid, command_key="review-source", **args)
    assert dev.create("scanner", "BMW|F900R|2025", command_key="scanner-source", **args) == item
    config = SchedulerConfig(reports=str(tmp_path / "pipeline"), log_file=str(tmp_path / "pipeline.log"))
    run((dev.config.database, config), result([ad()]))
    alerts = AlertService(dev.config).snapshot()["alerts"]
    alert = next(r for r in alerts if r["alert_type"] == "SEM_SUPORTE")
    assert dev.create("alert", alert["id"], command_key="alert-source", **args) == item
    assert dev.detail(item)["origins"][0]["alert_id"] == alert["id"]
    assert len(dev.detail(item)["origins"]) == 2


def test_manual_scanner_notification_visible_in_center(dev):
    dev.create(
        "scanner",
        "BMW|F900R|2025",
        actor="Teste",
        justification="Conferido",
        reason="UNSUPPORTED",
        confirmed=True,
        priority="high",
        command_key="scanner",
    )
    alerts = AlertService(dev.config)
    row = alerts.snapshot()["alerts"][0]
    assert row["alert_type"] == "DEV_NEW"
    alerts.transition(row["id"], "LIDO")
    assert alerts.history(row["id"])[-1]["after_status"] == "LIDO"


def test_incomplete_identity_refuses_creation(dev, tmp_path):
    coverage(dev.config.database, [ad(external_id="bad", year=None)], tmp_path / "bad")
    with pytest.raises(ValueError, match="Identidade incompleta"):
        create(dev, "bad")


def test_new_observation_updates_existing_item_dates_and_image(dev, tmp_path):
    item = create(dev, "2")
    coverage(
        dev.config.database,
        [
            ad(
                external_id="2",
                model="NOVA 900",
                collected_at="2026-09-25T12:00:00+00:00",
                primary_image_url="https://example.test/photo.jpg",
            )
        ],
        tmp_path / "later",
    )
    assert create(dev, "2") == item
    detail = dev.detail(item)
    assert detail["last_seen_at"] == "2026-09-25T12:00:00+00:00"
    assert detail["origins"][0]["occurrence_count"] == 2
    assert detail["primary_image_url"] == "https://example.test/photo.jpg"
    assert detail["revision"] == 2
    assert dev.listing(filters={"photo": ["with"]})["total"] == 1


def test_no_alerts_when_policy_disabled_and_sla_scan_throttled(dev):
    service = DevelopmentService(dev.config, policy=dev.policy | {"alerts_enabled": False})
    create(service, priority="high")
    assert not AlertService(dev.config).snapshot()["alerts"]
    assert scan_stale(dev.config.database, service.policy, force=True) == 0
    scan_stale(dev.config.database, dev.policy)
    with sqlite3.connect(dev.config.database) as db:
        before = list(db.iterdump())
    assert scan_stale(dev.config.database, dev.policy) == 0
    with sqlite3.connect(dev.config.database) as db:
        assert list(db.iterdump()) == before


def test_dashboard_explicit_creation_and_stale_form(dev, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("MOTO_DB", str(dev.config.database))
    monkeypatch.setenv("MOTO_READ_ONLY", "0")
    ui = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    ui.radio(key="navigation").set_value("Fila de revisão").run()
    rid = next(r["id"] for r in DashboardService(dev.config).snapshot()["queue"] if r["external_id"] == "2")
    ui.selectbox(key="review_selection").set_value(rid).run()
    ui.text_input(key=f"dev_actor_review_{rid}").set_value("Teste UI")
    ui.text_area(key=f"dev_note_review_{rid}").set_value("Necessidade avaliada")
    next(b for b in ui.button if b.label == "Confirmar inclusão").click().run()
    assert any("Confirme explicitamente" in e.value for e in ui.error)
    assert dev.listing()["total"] == 0
    ui.checkbox(key=f"dev_confirm_review_{rid}").check()
    next(b for b in ui.button if b.label == "Confirmar inclusão").click().run()
    item = dev.listing()["items"][0]["id"]
    ui.radio(key="navigation").set_value("Motos para desenvolvimento").run()
    ui.selectbox(key="development_selection").set_value(item).run()
    change(dev, item, "priority", "low")
    next(t for t in ui.text_input if t.label == "Autor da alteração").set_value("Teste UI")
    next(t for t in ui.text_area if t.label == "Justificativa da alteração").set_value("Conferido")
    next(b for b in ui.button if b.label == "Registrar alteração").click().run()
    assert any("outra operação" in e.value for e in ui.error)
    assert dev.detail(item)["status"] == "NEW"


def test_development_image_reuses_bounded_existing_loader(dev, monkeypatch, tmp_path):
    from dataclasses import replace as change_config
    from io import BytesIO

    from PIL import Image

    from services import vehicle_images
    from services.vehicle_image_config import load_image_config

    output = BytesIO()
    Image.new("RGB", (100, 80), "gray").save(output, "JPEG")
    calls = []
    monkeypatch.setattr(vehicle_images, "download_thumbnail", lambda *a: calls.append(a[0]) or output.getvalue())
    config = change_config(load_image_config(), cache_enabled=False)
    rows = [{"development_item": True, "primary_image_url": f"https://example.test/{n}.jpg"} for n in range(20)]
    results = vehicle_images.visible_photos(rows, config, cache_dir=tmp_path)
    assert len(results) == len(calls) == 8 and all(p.content for p in results)


def test_mutation_failure_rolls_back_status_and_events(dev, monkeypatch):
    item = create(dev)
    before = dev.detail(item)
    monkeypatch.setattr(DevelopmentRepository, "event", lambda *a: (_ for _ in ()).throw(RuntimeError("fixture")))
    with pytest.raises(RuntimeError):
        change(dev, item, "status", "UNDER_ANALYSIS")
    assert dev.detail(item) == before


def test_uncertain_identities_do_not_merge_across_ads_or_claim_support(dev, monkeypatch):
    source = dev.source("advertisement", "1")
    source["scanner"] = None
    source["effective"] = {"match_type": "AMBIGUOUS", "requires_review": True, "scanner_key": None}

    def uncertain(kind, identifier):
        return {**source, "advertisement": {**source["advertisement"], "external_id": str(identifier)}}

    monkeypatch.setattr(dev, "source", uncertain)
    first = create(dev, "1")
    second = create(dev, "2")
    assert first != second
    assert dev.detail(first)["current_scanner"] is None
    assert not dev.detail(first)["absence_confirmed_current"]


def test_migration_11_failure_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "previous.sqlite3"
    with sqlite3.connect(path) as db:
        for migration in sorted(Path("database/migrations").glob("*.sql")):
            if migration.name.startswith("011"):
                break
            db.executescript(migration.read_text(encoding="utf-8"))
            db.execute("INSERT OR IGNORE INTO schema_version VALUES (?)", (int(migration.name[:3]),))
    original = Path.read_text

    def broken(p, *a, **kw):
        content = original(p, *a, **kw)
        return content + "\nINVALID SQL;" if p.name == "011_development.sql" else content

    monkeypatch.setattr(Path, "read_text", broken)
    with pytest.raises(sqlite3.OperationalError):
        SQLiteRepository(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 10
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'development_%'").fetchall()


def test_readonly_change_and_alert_transition_are_rejected(dev):
    item = create(dev, priority="high")
    readonly = DevelopmentService(replace(dev.config, read_only=True))
    with pytest.raises(ValueError, match="somente leitura"):
        change(readonly, item, "note", "Teste")
    alerts = AlertService(replace(dev.config, read_only=True))
    with pytest.raises(ValueError, match="somente leitura"):
        alerts.transition(alerts.snapshot()["alerts"][0]["id"], "RESOLVIDO")


def test_photo_changes_do_not_change_development_identity(dev, tmp_path):
    item = create(dev, "2", priority="low")
    coverage(
        dev.config.database,
        [
            ad(
                external_id="2",
                model="NOVA 900",
                primary_image_url="https://example.test/new.jpg",
                collected_at="2026-09-26T00:00:00+00:00",
            )
        ],
        tmp_path / "new-photo",
    )
    assert create(dev, "2") == item
    assert dev.detail(item)["priority"] == "low"
    assert dev.listing()["total"] == 1


@pytest.mark.parametrize("kwargs", [{"page": -1}, {"size": 100}, {"sort": "invalid"}, {"filters": {"unknown": ["x"]}}])
def test_invalid_query_parameters(dev, kwargs):
    with pytest.raises(ValueError):
        dev.listing(**kwargs)
