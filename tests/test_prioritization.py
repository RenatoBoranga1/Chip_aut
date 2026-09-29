"""Deterministic fixtures only; never evaluates or writes the operational database."""

import copy
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_development import create
from test_matching import motorcycle
from test_review_queue import ad, coverage, import_base

from app.prioritization import main
from database.prioritization_repository import operational_sources, reading
from services.alert_service import AlertService
from services.dashboard_service import DashboardConfig, DashboardService
from services.development_service import DevelopmentService
from services.prioritization_engine import assess
from services.prioritization_policy import load_policy, validate_policy
from services.prioritization_service import PrioritizationService, safe_refresh

NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)


def source(**kwargs):
    result = {
        "partner": "wr_motos",
        "manufacturer": "BMW",
        "model": "F 900 R",
        "year": 2025,
        "effective_type": "CONFIRMADO_AUSENTE_NA_BASE",
        "human_status": "Não existe na base",
        "coverage": None,
        "first_seen": (NOW - timedelta(days=60)).isoformat(),
        "last_seen": NOW.isoformat(),
        "pending_since": (NOW - timedelta(days=40)).isoformat(),
        "observations": 5,
        "distinct_observation_days": 3,
        "development_known": True,
        "development": None,
        "scanner_base_version": 1,
        "source_snapshot_id": 1,
        "partner_status": "Já conhecido",
    }
    return result | kwargs


def evaluate(**kwargs):
    return assess(source(**kwargs), load_policy(), NOW)


def test_deterministic_explanation_sums_score():
    first = evaluate()
    assert first == evaluate()
    assert first["score"] == 90
    assert sum(r["points"] for r in first["reasons"]) == first["score"]
    assert first["suggested_priority"] == "high" and first["confidence"] == "sufficient"
    assert "suporte ausente" not in " ".join(r["reason"] for r in first["reasons"])


@pytest.mark.parametrize(
    "effective,coverage,human,reason",
    [
        ("CONFIRMADO_AUSENTE_NA_BASE", None, "Não existe na base", "Ausência confirmada"),
        ("NAO_ENCONTRADA_NA_BASE", None, "Pendente", "Não encontrada automaticamente"),
        ("AMBIGUOUS", None, "Pendente", "ambígua"),
        ("EXATO_CONFIRMADO_HUMANAMENTE", "SEM_SUPORTE", "Existe na base", "suporte ausente"),
        ("EXATO_NORMALIZADO", "SUPORTE_PARCIAL", "Pendente", "suporte parcial"),
        ("EXATO_NORMALIZADO", "SEM_STATUS", "Pendente", "não definido"),
        ("CONFIRMADO_MANUALMENTE", "SUPORTADO", "Existe na base", "suporte declarado"),
    ],
)
def test_distinct_base_meanings(effective, coverage, human, reason):
    result = evaluate(effective_type=effective, coverage=coverage, human_status=human)
    assert reason in result["reasons"][0]["reason"]
    if coverage == "SUPORTADO":
        assert result["score"] == 0
    if effective in {"NAO_ENCONTRADA_NA_BASE", "AMBIGUOUS"}:
        assert result["confidence"] == "partial"


@pytest.mark.parametrize(
    "missing", [{"manufacturer": None}, {"model": None}, {"year": None}, {"effective_type": "AGUARDANDO_MATCHING"}]
)
def test_missing_identity_or_comparison_is_unassessed(missing):
    result = evaluate(**missing)
    assert result["score"] is None and result["suggested_priority"] == "unassessed"
    assert result["confidence"] == "insufficient" and result["limitations"]


@pytest.mark.parametrize("bad", [-1, True, float("nan"), float("inf"), "30", 101])
def test_invalid_weight(bad):
    policy = load_policy()
    policy["weights"]["base_status"] = bad
    with pytest.raises(ValueError):
        validate_policy(policy)


@pytest.mark.parametrize(
    "change",
    [
        {"version": 2},
        {"version": True},
        {"score_max": 90},
        {"enabled": 1},
        {"stale_after_hours": -1},
        {"reassess_hours": 25},
        {"thresholds": {"high": 40, "medium": 45}},
        {"thresholds": {}},
        {"weights": {}},
        {"base_factors": {}},
    ],
)
def test_invalid_configuration(change):
    with pytest.raises(ValueError):
        validate_policy(load_policy() | change)


def test_incomplete_config_and_zero_weights_rejected():
    policy = load_policy()
    del policy["version"]
    with pytest.raises(ValueError):
        validate_policy(policy)
    policy = load_policy()
    policy["weights"] = {k: 0 for k in policy["weights"]}
    with pytest.raises(ValueError):
        validate_policy(policy)


@pytest.mark.parametrize(
    "score,expected", [(0, "low"), (44, "low"), (45, "medium"), (74, "medium"), (75, "high"), (100, "high")]
)
def test_boundaries_and_normalization(score, expected):
    policy = load_policy()
    policy["weights"] = {k: 100 if k == "base_status" else 0 for k in policy["weights"]}
    policy["base_factors"]["confirmed_absent"] = score / 100
    result = assess(source(), policy, NOW)
    assert result["score"] == score and result["suggested_priority"] == expected


def test_repeated_runs_do_not_imply_independent_demand():
    assert evaluate(observations=5)["score"] == evaluate(observations=5000)["score"]
    result = evaluate(distinct_observation_days=1, observations=5000)
    assert not any(r["criterion"] == "recurrence" for r in result["reasons"])


def test_unknown_dates_do_not_award_time_points():
    result = evaluate(first_seen=None, last_seen=None, pending_since=None)
    assert result["confidence"] == "partial"
    assert not {"recurrence", "pending_time", "data_quality"} & {r["criterion"] for r in result["reasons"]}


def test_correlated_alerts_and_image_year_do_not_inflate():
    base = evaluate()
    changed = evaluate(
        alert_types=["NOVO_ANUNCIO", "POSSIVEL_NOVA_MOTO", "SEM_SUPORTE"] * 100,
        primary_image_url="https://example.test/test.jpg",
        year=2026,
    )
    assert changed["score"] == base["score"] and changed["confidence"] == base["confidence"]


def test_return_and_stale_fact_capped_to_one_additional_signal():
    result = evaluate(partner_status="Reapareceu", decision_stale=True, alert_types=["DECISAO_DESATUALIZADA"] * 10)
    assert result["score"] == 100
    assert len([r for r in result["reasons"] if r["criterion"] == "operational_evidence"]) == 1


@pytest.mark.parametrize(
    "state", ["NEW", "WAITING_INFORMATION", "IN_DEVELOPMENT", "IN_VALIDATION", "COMPLETED", "DISCARDED"]
)
def test_development_states_are_evidence_not_commands(state):
    data = source(development={"id": 1, "status": state, "status_since": NOW.isoformat()})
    before = copy.deepcopy(data)
    result = assess(data, load_policy(), NOW)
    assert data == before
    assert result["score"] < evaluate()["score"]


@pytest.fixture
def priority(tmp_path):
    path = tmp_path / "priority.sqlite3"
    import_base(path, [motorcycle(status="SEM_SUPORTE")])
    ads = [ad(external_id=str(i), collected_at=(NOW - timedelta(days=60)).isoformat()) for i in range(1, 11)]
    coverage(path, ads, tmp_path / "first")
    coverage(path, [replace(a, collected_at=NOW.isoformat()) for a in ads], tmp_path / "second")
    return PrioritizationService(DashboardConfig(path), clock=lambda: NOW)


def dump(path):
    with reading(path) as db:
        return list(db.iterdump())


def test_refresh_history_no_duplicates_and_pagination(priority):
    result = priority.refresh()
    assert result["evaluated"] == result["changed"] == 10
    assert priority.refresh()["changed"] == 0
    rows = priority.listing()
    assert len(rows["items"]) == 8 and rows["total"] == 10
    assert len(priority.listing(page=1)["items"]) == 2
    assert not {r["id"] for r in rows["items"]} & {r["id"] for r in priority.listing(page=1)["items"]}
    assert len(priority.detail(rows["items"][0]["id"])["history"]) == 1
    assert priority.listing(sort="model")["items"] == priority.listing(sort="model")["items"]
    with reading(priority.config.database) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_manual_priority_survives_recalculation_and_restore(priority):
    priority.refresh()
    row = priority.listing()["items"][0]
    command = dict(
        author="Teste", reason="Sequência operacional escolhida", request_key="manual", revision=row["revision"]
    )
    priority.override(row["id"], "low", **command)
    priority.override(row["id"], "low", **command)
    priority.clock = lambda: NOW + timedelta(days=1)
    priority.refresh()
    current = priority.detail(row["id"])
    assert current["manual_priority"] == current["effective_priority"] == "low"
    assert len(current["overrides"]) == 1
    with pytest.raises(ValueError, match="alterada"):
        priority.override(row["id"], "high", **(command | {"request_key": "stale"}))
    priority.override(row["id"], None, **(command | {"request_key": "restore", "revision": current["revision"]}))
    assert priority.detail(row["id"])["manual_priority"] is None
    assert len(priority.detail(row["id"])["overrides"]) == 2


@pytest.mark.parametrize("changes", [{"author": ""}, {"reason": ""}, {"priority": "urgent"}])
def test_manual_validation(priority, changes):
    priority.refresh()
    row = priority.listing()["items"][0]
    kwargs = dict(priority="high", author="Teste", reason="Conferido", request_key="x", revision=row["revision"])
    before = dump(priority.config.database)
    with pytest.raises(ValueError):
        priority.override(row["id"], **(kwargs | changes))
    assert dump(priority.config.database) == before


def test_simulation_and_rendering_are_read_only(priority):
    priority.refresh()
    before = dump(priority.config.database)
    policy = copy.deepcopy(priority.policy)
    policy["weights"]["base_status"] = 100
    result = priority.simulate(policy)
    assert result["evaluated"] == 10
    priority.listing(filters={"manufacturer": ["BMW"]}, sort="pending")
    priority.detail(1)
    assert dump(priority.config.database) == before


def test_policy_version_saved_and_modified_weights_recalculate(priority):
    priority.refresh()
    priority.policy["weights"]["base_status"] = 40
    assert priority.listing()["stale"]
    assert priority.refresh()["changed"] == 10
    history = priority.detail(1)["history"]
    assert len(history) == 2
    assert json.loads(history[0]["payload_json"])["policy"]["weights"]["base_status"] == 40
    assert json.loads(history[1]["payload_json"])["policy"]["weights"]["base_status"] == 30


def test_review_and_development_hooks_preserve_business_decisions(priority):
    priority.refresh()
    dashboard = DashboardService(priority.config)
    review = dashboard.snapshot()["queue"][0] if dashboard.snapshot()["queue"] else None
    # Exact unsupported rows may still have queue entries; use a new unmatched identity.
    path = priority.config.database
    coverage(path, [ad(model="NOVA 900", collected_at=NOW.isoformat())], path.parent / "missing")
    priority.refresh()
    review = next(r for r in dashboard.snapshot()["queue"] if r["external_id"] == "1")
    item = dashboard.detail(review["id"])
    dashboard.submit(item["id"], "NAO_EXISTE_NA_BASE", "Pessoa", "Ausência conferida", None, "review", item["revision"])
    rows = priority.listing()["items"]
    assert rows[0]["human_status"] == "Não existe na base"
    assert rows[0]["evidence"]["coverage"] is None
    dev = DevelopmentService(priority.config)
    task = create(dev)
    assert priority.listing()["items"][0]["has_development"]
    old = dev.detail(task)
    priority.refresh()
    new = dev.detail(task)
    assert (old["priority"], old["status"], old["assigned_to"]) == (new["priority"], new["status"], new["assigned_to"])


def test_scheduler_reevaluates_activated_only(priority):
    safe_refresh(priority.config.database)
    assert not priority.listing()["installed"]
    priority.refresh()
    with sqlite3.connect(priority.config.database) as db:
        db.execute("UPDATE priority_maintenance SET checked_at='2000-01-01T00:00:00+00:00'")
    safe_refresh(priority.config.database)
    with reading(priority.config.database) as db:
        assert db.execute("SELECT checked_at FROM priority_maintenance").fetchone()[0][:4] != "2000"


def test_alert_deduplication_and_no_fake_pipeline(priority):
    priority.policy["thresholds"]["high"] = 65
    with reading(priority.config.database) as db:
        before = db.execute("SELECT count(*) FROM pipeline_runs").fetchone()[0]
    priority.refresh()
    service = AlertService(priority.config)
    alerts = [r for r in service.snapshot()["alerts"] if isinstance(r["id"], str)]
    assert alerts
    priority.refresh()
    assert [r for r in service.snapshot()["alerts"] if isinstance(r["id"], str)] == alerts
    service.transition(alerts[0]["id"], "LIDO")
    assert service.history(alerts[0]["id"])[0]["after_status"] == "LIDO"
    with reading(priority.config.database) as db:
        assert db.execute("SELECT count(*) FROM pipeline_runs").fetchone()[0] == before


def test_immutable_history_and_readonly_commands(priority):
    priority.refresh()
    with sqlite3.connect(priority.config.database) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM priority_assessments")
    readonly = PrioritizationService(replace(priority.config, read_only=True))
    with pytest.raises(ValueError, match="somente leitura"):
        readonly.refresh()
    with pytest.raises(ValueError, match="somente leitura"):
        readonly.override(1, "high", author="a", reason="b", request_key="c", revision=1)


def test_partner_registry_and_filters(priority):
    priority.refresh()
    with pytest.raises(ValueError, match="desconhecido"):
        PrioritizationService(replace(priority.config, partner="not_registered"))
    assert priority.listing(filters={"partner": ["other"]})["total"] == 0
    assert priority.listing(filters={"year": [2025]}, text="BMW")["total"] == 10
    assert priority.listing(filters={"has_development": [True]})["total"] == 0
    assert priority.listing(filters={"photo": ["with"]})["total"] == 0


def test_dashboard_and_cli_no_writes_on_navigation(priority, monkeypatch):
    priority.refresh()
    monkeypatch.setenv("MOTO_DB", str(priority.config.database))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    before = dump(priority.config.database)
    app = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Priorização operacional").run()
    assert not app.exception and not app.error
    assert next(b for b in app.button if b.label == "Reavaliar casos").disabled
    next(s for s in app.selectbox if s.label == "Ver motivos da avaliação").set_value(1).run()
    assert not app.exception and not app.error
    assert next(b for b in app.button if b.label == "Salvar prioridade").disabled
    assert main(["list", "--db", str(priority.config.database)]) == 0
    assert main(["refresh", "--db", str(priority.config.database)]) == 1
    assert dump(priority.config.database) == before


def test_sources_exclude_image_from_score_and_reuse_existing_review(priority):
    sources = operational_sources(priority.config.database, "wr_motos")
    assert len(sources) == 10 and sources[0]["observations"] >= 2
    result = assess(sources[0], load_policy(), NOW)
    assert result["score"] >= 0
    assert assess(sources[0] | {"primary_image_url": "anything"}, load_policy(), NOW)["score"] == result["score"]


def test_collection_hook_and_failed_collection_preserve_assessment(priority):
    from partners.models import CollectionResult
    from services.pipeline_service import run_pipeline
    from services.scheduler_config import SchedulerConfig

    priority.refresh()
    config = SchedulerConfig(
        reports=str(priority.config.database.parent / "pipeline"),
        log_file=str(priority.config.database.parent / "pipeline.log"),
        max_retries=0,
    )

    class Collector:
        def collect_motorcycles(self):
            return CollectionResult(
                "wr_motos",
                NOW.isoformat(),
                advertisements=[ad(model="NOVA 900", collected_at=NOW.isoformat())],
                complete=True,
            )

    result = run_pipeline(priority.config.database, config, collector_factory=lambda *_: Collector())
    assert result["status"] == "SUCCESS"
    assert priority.listing()["total"] == 1 and priority.listing()["items"][0]["model"] == "NOVA 900"
    before = priority.listing()["items"][0]["assessment_id"]

    class Broken:
        def collect_motorcycles(self):
            raise ValueError("fixture failure")

    assert run_pipeline(priority.config.database, config, collector_factory=lambda *_: Broken())["status"] == "FAILED"
    assert priority.listing()["items"][0]["assessment_id"] == before


def test_new_base_invalidates_human_absence_without_changing_decision(priority):
    path = priority.config.database
    coverage(path, [ad(model="NOVA 900")], path.parent / "missing2")
    dashboard = DashboardService(priority.config)
    item = dashboard.detail(next(r["id"] for r in dashboard.snapshot()["queue"] if r["external_id"] == "1"))
    dashboard.submit(item["id"], "NAO_EXISTE_NA_BASE", "Teste", "Conferida", None, "decision2", item["revision"])
    priority.refresh()
    assert priority.listing()["items"][0]["human_status"] == "Não existe na base"
    with reading(path) as db:
        decision = tuple(db.execute("SELECT * FROM review_decisions").fetchone())
    import_base(path, [motorcycle(), motorcycle("NOVA 900")])
    safe_refresh(path)
    assert priority.listing()["items"][0]["human_status"] == "Pendente"
    with reading(path) as db:
        assert tuple(db.execute("SELECT * FROM review_decisions").fetchone()) == decision


def test_disabled_feature_and_stale_manual_form(priority):
    priority.refresh()
    row = priority.listing()["items"][0]
    policy = priority.policy | {"enabled": False}
    disabled = PrioritizationService(priority.config, policy)
    before = dump(priority.config.database)
    assert disabled.refresh()["disabled"]
    assert dump(priority.config.database) == before
    import_base(priority.config.database, [motorcycle()])
    with pytest.raises(ValueError, match="reavalie"):
        priority.override(row["id"], "high", author="a", reason="b", request_key="obsolete", revision=row["revision"])


def test_atomic_refresh_failure_preserves_assessments(priority, monkeypatch):
    from database.prioritization_repository import PrioritizationRepository

    priority.refresh()
    before = dump(priority.config.database)
    priority.clock = lambda: NOW + timedelta(days=2)

    def fail(*args, **kwargs):
        raise RuntimeError("fixture persistence failure")

    monkeypatch.setattr(PrioritizationRepository, "save", fail)
    with pytest.raises(RuntimeError):
        priority.refresh()
    assert dump(priority.config.database) == before


def test_alerts_suppressed_for_existing_development(priority):
    dev = DevelopmentService(priority.config)
    for i in range(1, 11):
        create(dev, str(i))
    priority.policy["thresholds"] = {"high": 2, "medium": 1}
    priority.refresh()
    with reading(priority.config.database) as db:
        assert db.execute("SELECT count(*) FROM priority_alerts").fetchone()[0] == 0


def test_stale_notice_deduplicated_and_history_recorded(priority):
    priority.policy["thresholds"]["high"] = 65
    priority.refresh()
    priority.clock = lambda: NOW + timedelta(days=2)
    priority.refresh()
    with reading(priority.config.database) as db:
        count = db.execute("SELECT count(*) FROM priority_alerts WHERE alert_type='PRIORITY_OUTDATED'").fetchone()[0]
    assert count == 10
    priority.refresh()
    with reading(priority.config.database) as db:
        assert (
            db.execute("SELECT count(*) FROM priority_alerts WHERE alert_type='PRIORITY_OUTDATED'").fetchone()[0]
            == count
        )


def test_explicit_doubt_remains_pending_even_after_exact_automatic_match():
    result = evaluate(human_status="Em dúvida", effective_type="EXATO_NORMALIZADO", coverage="SEM_SUPORTE")
    assert result["awaiting_human"] and result["confidence"] == "partial"
    assert "dúvida" in result["reasons"][0]["reason"]
    assert "suporte ausente" not in result["reasons"][0]["reason"]
