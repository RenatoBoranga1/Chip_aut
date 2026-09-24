import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from test_matching import motorcycle
from test_pipeline import operational, result, run
from test_review_queue import ad, import_base

from database.alert_repository import AlertRepository, read_alerts
from database.pipeline_repository import read_pipeline
from database.review_repository import ReviewRepository
from services.alert_config import AlertConfig, load_alert_config
from services.alert_service import AlertService, filter_alerts, process_pending
from services.dashboard_service import DashboardConfig
from services.scheduler_config import SchedulerConfig
from ui.textos import ALERT_TYPES


@pytest.fixture
def setup(tmp_path):
    database = tmp_path / "test.sqlite3"
    import_base(database, [motorcycle(), motorcycle("F 900 R GT")])
    return database, SchedulerConfig(
        reports=str(tmp_path / "reports"),
        log_file=str(tmp_path / "pipeline.log"),
        heartbeat_seconds=0.1,
        retry_backoff_seconds=0,
    )


def alerts(setup, kind=None):
    rows = read_alerts(setup[0])["alerts"]
    return [r for r in rows if kind is None or r["alert_type"] == kind]


def one(setup, kind):
    found = alerts(setup, kind)
    assert len(found) == 1
    return found[0]


def support(setup, status):
    import_base(
        setup[0],
        [
            replace(
                motorcycle(status=status),
                supported_systems=["INJECAO"] if status != "SEM_SUPORTE" else [],
                unsupported_systems=["ABS"],
                unknown_systems=[],
            )
        ],
    )
    return run(setup)


def unmatched(**kwargs):
    return ad(manufacturer="MARCA NOVA", model="MODELO 900", **kwargs)


def test_new_ad_and_twelve_new_scenario(setup):
    first = run(setup, result([ad(external_id=str(i)) for i in range(12)]))
    assert first["summary"]["alerts"]["created"] == 12
    assert len(alerts(setup, "NOVO_ANUNCIO")) == 12
    second = run(setup, result([ad(external_id=str(i)) for i in range(12)]))
    assert second["summary"]["new"] == 0
    assert second["summary"]["alerts"]["created"] == 0
    assert all(r["occurrence_count"] == 1 for r in alerts(setup))


def test_supported_new_ad_is_info(setup):
    support(setup, "SUPORTADO")
    assert one(setup, "NOVO_ANUNCIO")["severity"] == "INFO"
    assert not alerts(setup, "SEM_SUPORTE")


def test_possible_new_is_not_unsupported_or_confirmed_absence(setup):
    run(setup, result([unmatched()]))
    item = one(setup, "POSSIVEL_NOVA_MOTO")
    assert item["severity"] == "ALTA" and item["scanner_key"] is None
    assert "não confirma" in item["message"]
    assert item["details"]["coverage"] == "NAO_ENCONTRADA_NA_BASE"
    assert not alerts(setup, "SEM_SUPORTE")
    assert one(setup, "REVISAO_ALTA_PRIORIDADE")["review_item_id"]


@pytest.mark.parametrize("kwargs", [{"year": None}, {"parse_warnings": ["ANO_INVALIDO"]}, {"model": None}])
def test_bad_identity_never_possible_new(setup, kwargs):
    run(setup, result([ad(manufacturer="MARCA NOVA", **kwargs)]))
    assert not alerts(setup, "POSSIVEL_NOVA_MOTO")


@pytest.mark.parametrize("status", ["SEM_SUPORTE", "SUPORTE_PARCIAL"])
def test_confirmed_identity_support_alerts_and_systems(setup, status):
    support(setup, status)
    item = one(setup, status)
    assert item["scanner_key"] == "BMW|F900R|2025"
    assert item["details"]["systems"]["unsupported_systems"] == ["ABS"]
    assert not alerts(setup, "POSSIVEL_NOVA_MOTO")


def test_ambiguous_candidate_with_no_support_is_not_support_alert(setup):
    import_base(setup[0], [motorcycle(status="SEM_SUPORTE"), motorcycle("F 900 R GT", status="SEM_SUPORTE")])
    run(setup)
    assert not alerts(setup, "SEM_SUPORTE")


def test_same_observation_and_request_are_idempotent(setup):
    support(setup, "SEM_SUPORTE")
    before = alerts(setup)
    run(setup, request_key="repeat")
    once = alerts(setup)
    run(setup, request_key="repeat")
    assert before == once == alerts(setup)


def test_new_observation_updates_once_without_duplicate_alert(setup):
    support(setup, "SEM_SUPORTE")
    second = result([ad(collected_at="2026-10-01T00:00:00+00:00")])
    run(setup, second)
    assert one(setup, "SEM_SUPORTE")["occurrence_count"] == 2
    run(setup, second)
    assert one(setup, "SEM_SUPORTE")["occurrence_count"] == 2


def test_new_review_not_repeated_active(setup):
    run(setup, result([unmatched()]))
    run(setup, result([unmatched(collected_at="2026-10-01T00:00:00+00:00")]))
    assert one(setup, "REVISAO_ALTA_PRIORIDADE")["occurrence_count"] == 1


@pytest.mark.parametrize("target", ["LIDO", "NOVO", "ARQUIVADO", "RESOLVIDO"])
def test_actions_only_change_alert_state_with_audit(setup, target):
    run(setup)
    item = one(setup, "NOVO_ANUNCIO")
    before = operational(setup[0])
    service = AlertService(DashboardConfig(setup[0]))
    if target == "NOVO":
        service.transition(item["id"], "LIDO")
    service.transition(item["id"], target)
    assert one(setup, "NOVO_ANUNCIO")["status"] == target
    history = service.history(item["id"])
    assert history[0]["action"] == "CRIADO" and history[-1]["after_status"] == target
    assert operational(setup[0]) == before
    service.transition(item["id"], target)
    assert service.history(item["id"]) == history


@pytest.mark.parametrize("target", ["NOVO", "LIDO", "ARQUIVADO", "RESOLVIDO"])
def test_readonly_rejects_all_actions(setup, target):
    run(setup)
    with pytest.raises(ValueError):
        AlertService(DashboardConfig(setup[0], read_only=True)).transition(alerts(setup)[0]["id"], target)


def test_archive_not_reopened_continuous_but_return_reopens(setup):
    support(setup, "SEM_SUPORTE")
    service = AlertService(DashboardConfig(setup[0]))
    item = one(setup, "SEM_SUPORTE")
    service.transition(item["id"], "ARQUIVADO")
    run(setup, result([ad(collected_at="2026-10-01T00:00:00+00:00")]))
    assert one(setup, "SEM_SUPORTE")["status"] == "ARQUIVADO"
    run(setup, result([]))
    assert not one(setup, "SEM_SUPORTE")["condition_active"]
    run(setup, result([ad(collected_at="2026-10-02T00:00:00+00:00")]))
    assert one(setup, "SEM_SUPORTE")["status"] == "NOVO"
    assert any(h["action"] == "REABERTO" for h in service.history(item["id"]))


@pytest.mark.parametrize("target", ["ARQUIVADO", "RESOLVIDO"])
def test_explicit_reopen(setup, target):
    run(setup)
    service = AlertService(DashboardConfig(setup[0]))
    item = alerts(setup)[0]
    service.transition(item["id"], target)
    with pytest.raises(ValueError):
        service.transition(item["id"], "LIDO")
    service.transition(item["id"], "NOVO")
    assert service.history(item["id"])[-1]["action"] == "REABERTO"


def test_wrong_partner_and_invalid_action_rejected(setup):
    run(setup)
    item = alerts(setup)[0]
    with pytest.raises(ValueError):
        AlertService(DashboardConfig(setup[0], partner="other")).transition(item["id"], "LIDO")
    with pytest.raises(ValueError):
        AlertService(DashboardConfig(setup[0])).transition(item["id"], "INVALID")


def failure(setup):
    return run(setup, result([], False, [{"code": "AccessDenied", "detail": "HTTP 403"}]))


def test_recurrent_failure_escalates_and_resets(setup):
    for number in range(1, 6):
        failure(setup)
        severity = "CRITICA" if number >= 5 else "ALTA" if number >= 3 else "ATENCAO"
        for kind in ("FALHA_PIPELINE", "FALHA_COLETA"):
            item = one(setup, kind)
            assert item["severity"] == severity and item["occurrence_count"] == number
    run(setup)
    assert not one(setup, "FALHA_PIPELINE")["condition_active"]
    failure(setup)
    assert one(setup, "FALHA_PIPELINE")["severity"] == "ATENCAO"


def test_pipeline_failure_without_collection_failure(setup, monkeypatch):
    from services import pipeline_service

    monkeypatch.setattr(
        pipeline_service, "build_coverage", lambda *a: (_ for _ in ()).throw(ValueError("secret trace"))
    )
    outcome = run(setup)
    assert outcome["status"] == "FAILED"
    assert one(setup, "FALHA_PIPELINE")["details"]["stage"] == "publication"
    assert "secret" not in json.dumps(alerts(setup))
    assert not alerts(setup, "FALHA_COLETA") and not alerts(setup, "NOVO_ANUNCIO")


def test_partial_collection_alert_without_operational_changes(setup):
    run(setup)
    before = operational(setup[0])
    run(setup, result([ad(external_id="unpublished")], False))
    assert one(setup, "COLETA_PARCIAL")["details"]["published"] is False
    assert operational(setup[0]) == before
    assert len(alerts(setup, "NOVO_ANUNCIO")) == 1


def test_success_with_warnings_labeled_published(setup):
    run(setup, result([ad(parse_warnings=["FILTROS_ZERO_KM_CONFLITANTES"])]))
    item = one(setup, "COLETA_PARCIAL")
    assert item["details"]["published"] and not item["details"]["incomplete"]
    assert item["severity"] == "ATENCAO"


def test_alert_failure_rolls_back_batch_and_preserves_pipeline_then_recovers(setup, monkeypatch):
    original = AlertRepository.observe
    count = []

    def broken(self, *args):
        outcome = original(self, *args)
        count.append(1)
        if len(count) == 2:
            raise ValueError("fixture delivery failure")
        return outcome

    with monkeypatch.context() as patch:
        patch.setattr(AlertRepository, "observe", broken)
        outcome = run(setup, result([unmatched()]))
    assert outcome["status"] == "SUCCESS"
    assert outcome["summary"]["alert_error"]
    assert not alerts(setup) and read_alerts(setup[0])["pending"] == 1
    before = operational(setup[0])
    process_pending(setup[0])
    assert len(alerts(setup)) == 3 and read_alerts(setup[0])["pending"] == 0
    assert "alert_error" not in read_pipeline(setup[0])["runs"][0]["summary"]
    process_pending(setup[0])
    assert len(alerts(setup)) == 3 and operational(setup[0]) == before


def test_disabled_alerts_preserve_pipeline(setup, monkeypatch, tmp_path):
    config = tmp_path / "alerts.json"
    config.write_text('{"enabled": false}')
    monkeypatch.setenv("MOTO_ALERTS_CONFIG", str(config))
    outcome = run(setup)
    assert outcome["status"] == "SUCCESS" and outcome["summary"]["alerts"]["disabled"]
    assert not alerts(setup)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"enabled": "false"},
        {"failure_high_after": 0},
        {"failure_high_after": 5},
        {"failure_critical_after": 2},
        {"failure_high_after": True},
    ],
)
def test_config_validation(kwargs):
    with pytest.raises(ValueError):
        AlertConfig(**kwargs)


def test_config_default_valid():
    assert load_alert_config() == AlertConfig()


def test_stale_human_decision_and_new_base_are_auditable(setup):
    run(setup, result([unmatched()]))
    review_id = one(setup, "REVISAO_ALTA_PRIORIDADE")["review_item_id"]
    with ReviewRepository(setup[0]) as repo:
        repo.decide(review_id, "NAO_EXISTE_NA_BASE", "Fixture", "Synthetic review")
    run(setup, result([unmatched()]))
    import_base(setup[0], [motorcycle()])
    before = operational(setup[0])["review_decisions"]
    run(setup, result([unmatched()]))
    item = one(setup, "DECISAO_DESATUALIZADA")
    assert item["details"]["old_base_id"] == 1 and item["details"]["base_id"] == 2
    assert item["details"]["decision"] == "NAO_EXISTE_NA_BASE"
    assert one(setup, "NOVA_VERSAO_BASE")["details"]["base_id"] == 2
    run(setup, result([unmatched()]))
    assert one(setup, "DECISAO_DESATUALIZADA")["occurrence_count"] == 1
    assert operational(setup[0])["review_decisions"] == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("severity", "ALTA"),
        ("status", "NOVO"),
        ("alert_type", "POSSIVEL_NOVA_MOTO"),
        ("manufacturer", "MARCA NOVA"),
        ("partner", "wr_motos"),
    ],
)
def test_filters(setup, field, value):
    run(setup, result([unmatched()]))
    found = filter_alerts(alerts(setup), {field: [value]})
    assert found and all(r[field] == value for r in found)


def test_read_period_sort_filters(setup):
    failure(setup)
    run(setup, result([unmatched()]))
    rows = alerts(setup)
    assert not filter_alerts(rows, start="2999-01-01")
    assert not filter_alerts(rows, end="1900-01-01")
    assert len(filter_alerts(rows, read=False)) == len(rows)
    AlertService(DashboardConfig(setup[0])).transition(rows[0]["id"], "LIDO")
    assert len(filter_alerts(alerts(setup), read=True)) == 1
    assert filter_alerts(rows)[0]["severity"] == "ALTA"
    for order in ("recent", "oldest", "title"):
        assert len(filter_alerts(rows, sort=order)) == len(rows)


def test_history_append_only(setup):
    run(setup)
    with sqlite3.connect(setup[0]) as db:
        for query in ("UPDATE alert_history SET action='bad'", "DELETE FROM alert_history"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(query)


def test_read_missing_schema_no_migration(setup):
    with sqlite3.connect(setup[0]) as db:
        db.execute("DROP TABLE alerts")
    assert read_alerts(setup[0]) == {"alerts": [], "pending": 0}


def test_dashboard_actions_and_portuguese(setup, monkeypatch):
    from streamlit.testing.v1 import AppTest

    run(setup, result([unmatched()]))
    before = operational(setup[0])
    monkeypatch.setenv("MOTO_DB", str(setup[0]))
    monkeypatch.setenv("MOTO_READ_ONLY", "0")
    ui = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=20).run()
    ui.radio(key="navigation").set_value("Alertas").run()
    assert not ui.exception and not ui.error
    ui.selectbox(key="alert_selection").set_value(one(setup, "POSSIVEL_NOVA_MOTO")["id"]).run()
    for label in ("Marcar como lido", "Marcar como não lido", "Arquivar", "Reabrir", "Resolver", "Reabrir"):
        next(b for b in ui.button if b.label == label).click().run()
        assert not ui.exception and not ui.error
    assert operational(setup[0]) == before
    assert set(ALERT_TYPES) >= {r["alert_type"] for r in alerts(setup)}
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    ui.run()
    assert next(b for b in ui.button if b.label == "Arquivar").disabled


def test_migration_preserves_old_tables_and_integrity(setup):
    with sqlite3.connect(setup[0]) as db:
        assert db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 11
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_retries_count_one_failure_event_per_execution(setup):
    value = result([], False, [{"code": "Timeout", "detail": "timeout"}])
    outcome = run(setup, value)
    assert outcome["summary"]["attempts"] == 3
    assert one(setup, "FALHA_COLETA")["occurrence_count"] == 1
    assert one(setup, "FALHA_COLETA")["details"]["attempts"] == 3


def test_collection_failure_streak_is_separate(setup, monkeypatch):
    from services import pipeline_service

    failure(setup)
    with monkeypatch.context() as patch:
        patch.setattr(pipeline_service, "build_coverage", lambda *a: (_ for _ in ()).throw(ValueError("fixture")))
        run(setup)
    failure(setup)
    assert one(setup, "FALHA_PIPELINE")["severity"] == "ALTA"
    assert one(setup, "FALHA_COLETA")["severity"] == "ATENCAO"
    assert one(setup, "FALHA_COLETA")["details"]["consecutive_failures"] == 1


@pytest.mark.parametrize(
    "flag,kind",
    [
        ("new_ad_enabled", "NOVO_ANUNCIO"),
        ("probable_missing_enabled", "POSSIVEL_NOVA_MOTO"),
        ("high_priority_review_enabled", "REVISAO_ALTA_PRIORIDADE"),
    ],
)
def test_individual_rule_switches(setup, monkeypatch, tmp_path, flag, kind):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({flag: False}))
    monkeypatch.setenv("MOTO_ALERTS_CONFIG", str(config))
    run(setup, result([unmatched()]))
    assert not alerts(setup, kind)
    assert len(alerts(setup)) == 2


def test_custom_failure_thresholds(setup, monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"failure_high_after": 1, "failure_critical_after": 2}))
    monkeypatch.setenv("MOTO_ALERTS_CONFIG", str(config))
    failure(setup)
    assert one(setup, "FALHA_PIPELINE")["severity"] == "ALTA"
    failure(setup)
    assert one(setup, "FALHA_PIPELINE")["severity"] == "CRITICA"


def test_bad_alert_config_is_observable_and_recoverable(setup, monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"enabled": "invalid"}')
    monkeypatch.setenv("MOTO_ALERTS_CONFIG", str(config))
    outcome = run(setup)
    assert outcome["status"] == "SUCCESS" and outcome["summary"]["alert_error"]
    assert read_alerts(setup[0])["pending"] == 1
    config.write_text("{}")
    process_pending(setup[0])
    assert read_alerts(setup[0])["pending"] == 0


def test_concurrent_delivery_is_idempotent(setup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from services import pipeline_service

    with monkeypatch.context() as patch:
        patch.setattr(pipeline_service, "safe_process", lambda *a: None)
        run(setup, result([unmatched()]))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: process_pending(setup[0]), range(2)))
    assert len(alerts(setup)) == 3
    assert all(r["occurrence_count"] == 1 for r in alerts(setup))


def test_alert_to_review_and_pipeline_navigation(setup, monkeypatch):
    from streamlit.testing.v1 import AppTest

    run(setup, result([unmatched()]))
    monkeypatch.setenv("MOTO_DB", str(setup[0]))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    ui = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=20).run()
    for label, page in [
        ("Abrir item na fila", "Fila de revisão"),
        ("Abrir execução relacionada", "Atualização automática"),
    ]:
        ui.radio(key="navigation").set_value("Alertas").run()
        ui.selectbox(key="alert_selection").set_value(one(setup, "POSSIVEL_NOVA_MOTO")["id"]).run()
        next(b for b in ui.button if b.label == label).click().run()
        assert ui.radio(key="navigation").value == page
        assert not ui.exception and not ui.error


def test_legacy_existing_ads_not_reannounced_as_new(setup, tmp_path):
    from test_review_queue import coverage

    coverage(setup[0], [unmatched()], tmp_path / "old-report")
    run(setup, result([unmatched()]))
    assert not alerts(setup, "NOVO_ANUNCIO")
    assert not alerts(setup, "REVISAO_ALTA_PRIORIDADE")
    assert one(setup, "POSSIVEL_NOVA_MOTO")


def test_cli_pending_processing(setup):
    import subprocess
    import sys

    run(setup)
    before = alerts(setup)
    completed = subprocess.run([sys.executable, "-m", "app.alerts", "--db", str(setup[0])], capture_output=True)
    assert completed.returncode == 0, completed.stderr
    assert alerts(setup) == before
