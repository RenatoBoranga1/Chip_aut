import json
import sqlite3
import subprocess
import sys
import threading
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_matching import motorcycle
from test_review_queue import ad, import_base

from database.pipeline_repository import PipelineRepository, read_pipeline
from database.review_repository import ReviewRepository
from database.transaction import atomic_database
from partners.models import CollectionResult
from services.collection_service import collect_partners
from services.pipeline_lock import AlreadyRunning, ExecutionLock
from services.pipeline_service import run_pipeline, transient
from services.scheduler_config import SchedulerConfig, next_due, utcnow
from services.scheduler_service import launch_manual, scheduler_status, serve


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "test.sqlite3"
    import_base(path, [motorcycle(), motorcycle("F 900 R GT")])
    config = SchedulerConfig(
        reports=str(tmp_path / "reports"),
        log_file=str(tmp_path / "pipeline.log"),
        heartbeat_seconds=0.1,
        retry_backoff_seconds=0,
    )
    return path, config


def result(ads=None, complete=True, errors=None):
    return CollectionResult(
        "wr_motos",
        utcnow().isoformat(),
        advertisements=ads if ads is not None else [ad()],
        complete=complete,
        errors=errors or [],
    )


class Fake:
    def __init__(self, value):
        self.value = value

    def collect_motorcycles(self):
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


def run(setup, value=None, **kwargs):
    path, config = setup
    return run_pipeline(path, config, collector_factory=lambda *_: Fake(value or result()), **kwargs)


def operational(path):
    with sqlite3.connect(path) as db:
        tables = [
            "partner_advertisements",
            "partner_collections",
            "partner_observations",
            "matching_runs",
            "review_items",
            "review_decisions",
            "review_occurrences",
            "coverage_runs",
        ]
        return {t: db.execute("SELECT * FROM " + t).fetchall() for t in tables}


def test_complete_run_updates_all_layers(setup):
    r = run(setup)
    assert r["status"] == "SUCCESS"
    assert r["collection_run_id"]
    assert r["summary"]["matching_counts"] == {"AMBIGUOUS": 1}
    assert r["summary"]["queue_counts"]["items"] == 1
    assert r["summary"]["coverage_counts"]["REVISAR"] == 1
    assert r["summary"]["ads_before"] == 0 and r["summary"]["new"] == 1
    data = operational(setup[0])
    assert len(data["matching_runs"]) == 1 and len(data["review_items"]) == 1
    assert not data["review_decisions"]
    assert datetime.fromisoformat(r["started_at"]).utcoffset() == timedelta(0)
    assert r["duration_seconds"] >= 0 and r["finished_at"]


def test_same_observation_is_idempotent(setup):
    first = run(setup)
    before = operational(setup[0])
    second = run(setup, result())
    assert second["summary"]["reused"]
    assert first["collection_run_id"] == second["collection_run_id"]
    assert operational(setup[0]) == before
    assert len(read_pipeline(setup[0])["runs"]) == 2


def test_request_key_does_not_repeat_collection(setup):
    first = run(setup, request_key="button")

    def forbidden(*args):
        raise AssertionError("Repeated collection")

    second = run_pipeline(*setup, request_key="button", collector_factory=forbidden)
    assert first == second


@pytest.mark.parametrize("change", ["base", "decision", "price"])
def test_changed_input_recomputes(setup, change):
    first = run(setup)
    payload = result()
    if change == "base":
        import_base(setup[0], [motorcycle(status="SEM_SUPORTE")])
    elif change == "decision":
        with ReviewRepository(setup[0]) as repo:
            repo.decide(1, "CONFIRMAR_MATCH", "Teste", "Fixture", "BMW|F900R|2025")
    else:
        payload = result([ad(price="15000")])
    second = run(setup, payload)
    assert not second["summary"]["reused"]
    assert first["collection_run_id"] != second["collection_run_id"]
    with ReviewRepository(setup[0]) as repo:
        assert repo.connection.execute("SELECT COUNT(*) FROM review_items WHERE active=1").fetchone()[0] == 1
        if change == "decision":
            assert repo.show(1)["effective"]["match_type"] == "EXATO_CONFIRMADO_HUMANAMENTE"


def test_negative_memory_expires_on_new_base(setup):
    run(setup)
    with ReviewRepository(setup[0]) as repo:
        repo.decide(1, "NAO_EXISTE_NA_BASE", "Teste", "Fixture")
    import_base(setup[0], [motorcycle()])
    r = run(setup)
    with ReviewRepository(setup[0]) as repo:
        item = repo.show(1)
        assert item["effective"]["match_type"] != "CONFIRMADO_AUSENTE_NA_BASE"
        assert repo.connection.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 1
    assert r["status"] == "SUCCESS"


@pytest.mark.parametrize("partial", [False, True])
def test_failed_or_partial_collection_preserves_operational_state(setup, partial):
    run(setup)
    before = operational(setup[0])
    r = run(setup, result([ad(external_id="2")] if partial else [], False, [{"code": "UNPARSED_CARD"}]))
    assert r["status"] == "FAILED" and r["collection_run_id"] is None
    assert r["summary"]["disappeared"] is None
    assert operational(setup[0]) == before


@pytest.mark.parametrize(
    "code,detail,expected",
    [
        ("Timeout", "", True),
        ("ConnectionError", "", True),
        ("RuntimeError", "HTTP 503", True),
        ("AccessDeniedError", "HTTP 403", False),
        ("AccessDeniedError", "HTTP 429", False),
        ("AccessDeniedError", "HTTP 401", False),
        ("RuntimeError", "Contrato mudou", False),
        ("UNPARSED_CARD", "", False),
    ],
)
def test_retry_policy(code, detail, expected):
    assert transient([{"code": code, "detail": detail}]) is expected


def test_bounded_retry_and_recovery(setup):
    calls = []
    delays = []
    values = iter([result([], False, [{"code": "Timeout"}]), result()])

    def factory(*args):
        calls.append(1)
        return Fake(next(values))

    r = run_pipeline(*setup, collector_factory=factory, sleeper=delays.append)
    assert r["status"] == "PARTIAL_SUCCESS" and len(calls) == 2 and delays == [0]
    failed = run(setup, result([], False, [{"code": "Timeout"}]), sleeper=delays.append)
    assert failed["status"] == "FAILED" and failed["summary"]["attempts"] == 3


def test_block_does_not_retry(setup):
    r = run(setup, result([], False, [{"code": "AccessDeniedError", "detail": "HTTP 403"}]))
    assert r["status"] == "FAILED" and r["summary"]["attempts"] == 1


def test_os_lock_blocks_pipeline_and_legacy_collection(setup):
    path, config = setup
    with ExecutionLock(path):
        with pytest.raises(AlreadyRunning):
            with ExecutionLock(path):
                pass
        r = run(setup)
        assert r["status"] == "SKIPPED_ALREADY_RUNNING"
        with pytest.raises(AlreadyRunning):
            collect_partners({"wr_motos": Fake(result())}, path)
    assert run(setup)["status"] == "SUCCESS"


def test_live_lock_never_stolen_despite_old_heartbeat(setup):
    with PipelineRepository(setup[0]) as repo:
        old = repo.start("manual", setup[1].digest)
        with repo.connection:
            repo.connection.execute("UPDATE pipeline_runs SET heartbeat_at='2000-01-01T00:00:00+00:00'")
    with ExecutionLock(setup[0]):
        assert run(setup)["status"] == "SKIPPED_ALREADY_RUNNING"
    assert read_pipeline(setup[0], run_id=old)["runs"][0]["status"] == "RUNNING"
    assert run(setup)["status"] == "SUCCESS"
    assert read_pipeline(setup[0], run_id=old)["runs"][0]["status"] == "CANCELLED"


def test_os_releases_lock_when_process_dies(setup):
    code = "from services.pipeline_lock import ExecutionLock; import sys,time; lock=ExecutionLock(sys.argv[1]); lock.__enter__(); print('ready',flush=True); time.sleep(60)"
    child = subprocess.Popen([sys.executable, "-c", code, str(setup[0])], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        with pytest.raises(AlreadyRunning):
            with ExecutionLock(setup[0]):
                pass
    finally:
        child.terminate()
        child.wait(timeout=10)
    assert run(setup)["status"] == "SUCCESS"


def test_coverage_failure_rolls_back_collection_matching_and_queue(setup, monkeypatch):
    run(setup)
    before = operational(setup[0])
    from services import pipeline_service

    original = pipeline_service.build_coverage

    def fail(*args):
        original(*args)
        raise sqlite3.OperationalError("fixture disk failure")

    monkeypatch.setattr(pipeline_service, "build_coverage", fail)
    r = run(setup, result([ad(external_id="2")]))
    assert r["status"] == "FAILED" and operational(setup[0]) == before


def test_atomic_unit_rolls_back_even_swallowed_inner_error(setup):
    with pytest.raises(RuntimeError):
        with atomic_database(setup[0]):
            with PipelineRepository(setup[0]) as repo:
                try:
                    with repo.connection:
                        repo.connection.execute("INSERT INTO scheduler_state VALUES (1,'now',NULL,'hash','RUNNING')")
                        raise ValueError("inner")
                except ValueError:
                    pass
    assert read_pipeline(setup[0])["scheduler"] is None


def test_new_returned_disappeared_and_existing(setup):
    run(setup, result([ad(), ad(external_id="2")]))
    second = run(setup, result([ad(external_id="2"), ad(external_id="3")]))
    assert second["summary"]["new"] == 1 and second["summary"]["disappeared"] == 1
    third = run(setup, result([ad(), ad(external_id="2")]))
    assert third["summary"]["returned"] == 1 and third["summary"]["reappeared"] == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timezone": "missing/timezone"},
        {"enabled": "false"},
        {"hour": 24},
        {"minute": -1},
        {"frequency": "bad"},
        {"max_retries": 6},
        {"interval_hours": 0},
        {"delay_seconds": 1},
        {"heartbeat_seconds": 60, "activity_timeout_seconds": 90},
        {"interval_hours": float("nan")},
    ],
)
def test_invalid_config(kwargs):
    with pytest.raises((ValueError, KeyError)):
        SchedulerConfig(**kwargs)


def test_daily_interval_and_dst():
    cfg = SchedulerConfig()
    instant = datetime(2026, 9, 23, 9, tzinfo=timezone.utc)
    assert next_due(cfg, instant) == datetime(2026, 9, 23, 10, tzinfo=timezone.utc)
    assert next_due(cfg, next_due(cfg, instant)) == datetime(2026, 9, 24, 10, tzinfo=timezone.utc)
    assert next_due(replace(cfg, frequency="interval"), instant) - instant == timedelta(hours=12)
    dst = replace(cfg, timezone="America/New_York", hour=2, minute=30)
    assert next_due(dst, datetime(2026, 3, 8, 6, tzinfo=timezone.utc)) == datetime(
        2026, 3, 8, 7, 30, tzinfo=timezone.utc
    )
    with pytest.raises(ValueError):
        next_due(cfg, datetime(2026, 1, 1))


def test_scheduled_trigger_and_no_catchup_storm(setup, tmp_path):
    path, cfg = setup
    settings = tmp_path / "scheduler.json"
    settings.write_text(json.dumps(asdict(cfg)))
    now = utcnow()
    with PipelineRepository(path) as repo:
        repo.scheduler(cfg, now - timedelta(days=5), "RUNNING")
    calls = []

    def runner(db, config, **kwargs):
        calls.append(kwargs)
        return run_pipeline(db, config, collector_factory=lambda *_: Fake(result()), **kwargs)

    serve(path, settings, clock=lambda: now, runner=runner, max_ticks=1)
    assert len(calls) == 1 and calls[0]["trigger"] == "scheduled"
    assert read_pipeline(path)["runs"][0]["trigger_type"] == "scheduled"
    assert datetime.fromisoformat(read_pipeline(path)["scheduler"]["next_run_at"]) > now
    serve(path, settings, clock=lambda: now, runner=runner, max_ticks=1)
    assert len(calls) == 1


def test_disabled_allows_manual_and_readonly_blocks_launch(setup, tmp_path):
    path, cfg = setup
    cfg = replace(cfg, enabled=False)
    settings = tmp_path / "disabled.json"
    settings.write_text(json.dumps(asdict(cfg)))
    serve(path, settings, max_ticks=1)
    assert scheduler_status(path, cfg)["schedule_status"] == "DISABLED"
    assert run((path, cfg))["status"] == "SUCCESS"
    with pytest.raises(ValueError):
        launch_manual(path, settings, request_key="x", read_only=True)


def test_scheduler_observability_requires_recent_activity(setup):
    path, cfg = setup
    assert scheduler_status(path, cfg)["next_local"] is None
    with PipelineRepository(path) as repo:
        repo.scheduler(cfg, next_due(cfg, utcnow()), "RUNNING")
    assert scheduler_status(path, cfg)["schedule_status"] == "RUNNING"
    assert scheduler_status(path, cfg)["next_local"]
    with PipelineRepository(path) as repo:
        with repo.connection:
            repo.connection.execute("UPDATE scheduler_state SET heartbeat_at='2000-01-01T00:00:00+00:00'")
    assert scheduler_status(path, cfg)["schedule_status"] == "STALE_ACTIVITY"
    assert scheduler_status(path, cfg)["next_local"] is None


def test_missing_database_not_created(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(ValueError):
        run_pipeline(path, SchedulerConfig(log_file=str(tmp_path / "log")))
    assert not path.exists()


def test_cli_validation_and_history(setup, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(asdict(setup[1])))
    for command in ["validate-config", "status", "history"]:
        p = subprocess.run(
            [sys.executable, "-m", "app.scheduler", command, "--db", str(setup[0]), "--config", str(cfg)],
            capture_output=True,
        )
        assert p.returncode == 0, p.stderr


def test_fresh_unchanged_catalog_updates_last_seen_once_without_rematching(setup):
    run(setup)
    before = operational(setup[0])
    fresh = result([ad(collected_at="2026-10-01T00:00:00+00:00")])
    second = run(setup, fresh)
    assert second["summary"]["reused"]
    after = operational(setup[0])
    assert before["matching_runs"] == after["matching_runs"]
    assert before["review_occurrences"] == after["review_occurrences"]
    with sqlite3.connect(setup[0]) as db:
        assert db.execute("SELECT last_seen_at,verification_count FROM partner_advertisements").fetchone() == (
            "2026-10-01T00:00:00+00:00",
            2,
        )
    run(setup, fresh)
    assert operational(setup[0]) == after


def test_parallel_runs_only_one_collector_and_heartbeat(setup):
    from concurrent.futures import ThreadPoolExecutor

    entered = threading.Event()
    release = threading.Event()

    class Waiting:
        def collect_motorcycles(self):
            entered.set()
            assert release.wait(5)
            return result()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_pipeline, *setup, collector_factory=lambda *_: Waiting())
        assert entered.wait(5)
        first = read_pipeline(setup[0])["runs"][0]
        try:
            assert run(setup)["status"] == "SKIPPED_ALREADY_RUNNING"
            import time

            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                observed = read_pipeline(setup[0], run_id=first["id"])["runs"][0]
                if observed["heartbeat_at"] != first["heartbeat_at"]:
                    break
                time.sleep(0.02)
            assert observed["heartbeat_at"] != first["heartbeat_at"]
        finally:
            release.set()
        assert future.result()["status"] == "SUCCESS"


def test_database_failure_propagates_and_releases_lock(setup, monkeypatch):
    def failure(*args, **kwargs):
        raise sqlite3.OperationalError("fixture unavailable")

    with monkeypatch.context() as m:
        m.setattr(PipelineRepository, "start", failure)
        with pytest.raises(sqlite3.OperationalError):
            run(setup)
    with ExecutionLock(setup[0]):
        pass
    assert run(setup)["status"] == "SUCCESS"


def test_dashboard_sends_same_request_and_readonly_disables(setup, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from ui import pipeline_panel

    calls = []
    monkeypatch.setattr(pipeline_panel, "launch_manual", lambda *args, **kwargs: calls.append(kwargs))
    monkeypatch.setenv("MOTO_DB", str(setup[0]))
    monkeypatch.setenv("MOTO_READ_ONLY", "0")
    ui = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=20).run()
    ui.radio(key="navigation").set_value("Atualização automática").run()
    assert not ui.error and not ui.exception
    for _ in range(2):
        next(b for b in ui.button if b.label == "Executar atualização agora").click().run()
    assert len(calls) == 2 and calls[0]["request_key"] == calls[1]["request_key"]
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    ui.run()
    assert next(b for b in ui.button if b.label == "Executar atualização agora").disabled


def test_launch_uses_pipeline_process_with_no_window(setup, monkeypatch):
    from services import scheduler_service

    calls = []
    monkeypatch.setattr(scheduler_service.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    launch_manual(setup[0], request_key="fixture")
    args, kwargs = calls[0]
    assert args[0][1:3] == ["-m", "app.run_pipeline"]
    assert "--request-key" in args[0]
    assert kwargs["close_fds"]


def test_empty_complete_catalog_can_remove_but_partial_cannot(setup):
    run(setup)
    r = run(setup, result([], True))
    assert r["status"] == "SUCCESS" and r["summary"]["disappeared"] == 1
    with sqlite3.connect(setup[0]) as db:
        assert db.execute("SELECT not_seen_in_latest_collection FROM partner_advertisements").fetchone()[0] == 1


def test_concurrent_schema_upgrade_from_previous_version(setup):
    from concurrent.futures import ThreadPoolExecutor

    with sqlite3.connect(setup[0]) as db:
        db.executescript(
            "DROP TABLE scheduler_state; DROP TABLE pipeline_runs; DELETE FROM schema_version WHERE version=8;"
        )
    barrier = threading.Barrier(2)

    def open_repository(_):
        barrier.wait(timeout=5)
        with PipelineRepository(setup[0]) as repo:
            return repo.connection.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(open_repository, range(2))) == [8, 8]


def test_duplicate_busy_request_is_recorded_once(setup):
    from concurrent.futures import ThreadPoolExecutor

    with ExecutionLock(setup[0]), ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: run(setup, request_key="busy-request"), range(2)))
    assert rows[0]["id"] == rows[1]["id"]
    assert len(read_pipeline(setup[0])["runs"]) == 1
