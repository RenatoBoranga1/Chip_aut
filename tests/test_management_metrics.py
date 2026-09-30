"""Read-only analytics contracts, historical boundaries and non-inflating aggregates."""

import csv
import io
import sqlite3
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_matching import motorcycle
from test_review_queue import ad, coverage, import_base

from database.management_metrics_repository import ManagementMetricsRepository, stamp
from database.review_repository import ReviewRepository
from matching.review_policy import signature
from services.management_metrics_service import (
    FILTERS,
    ManagementMetricsService,
    accepts,
    bounds,
    calculate,
    csv_export,
    duration_stats,
    inside,
    period,
)

UTC = timezone.utc
START = datetime(2026, 9, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)


def instant(day):
    return f"2026-09-{day:02}T12:00:00+00:00"


def empty():
    return {
        "base_id": 1,
        "version": None,
        "base": [],
        "ads": [],
        "reviews": [],
        "decisions": [],
        "review_events": [],
        "development": [],
        "development_events": [],
        "origins": [],
        "priorities": [],
        "alerts": [],
        "coverage": [],
        "observations": [],
        "tables": [],
        "versions": [],
    }


def vehicle(key="1", **changes):
    return {
        "partner": "wr_motos",
        "external_id": key,
        "manufacturer": "BMW",
        "model": "F 900 R",
        "version": None,
        "year": 2025,
        "first_seen": instant(2),
        "active_at_end": True,
        **changes,
    }


def matching(kind="NAO_ENCONTRADA_NA_BASE", status=None):
    return {"match_type": kind, "scanner_status": status, "requires_review": kind != "EXATO_NORMALIZADO"}


def entry(advertisement, day=3, base=1, **changes):
    return {
        "advertisement": advertisement,
        "matching": matching(),
        "evaluated_at": instant(day),
        "import_id": base,
        "coverage_id": day,
        "collection_id": day,
        **changes,
    }


def report(data, filters=None):
    return calculate(data, START, END, filters or {}, {"IN_DEVELOPMENT": 3})


@pytest.fixture
def evidence():
    data = empty()
    a, b = vehicle(), vehicle("2")
    data["ads"] = [a, b]
    data["coverage"] = [entry(a), entry(b)]
    data["observations"] = [
        {"payload": {**a, "collected_at": instant(4)}},
        {"payload": {**a, "collected_at": instant(5)}},
        {"payload": {**b, "collected_at": instant(5)}},
    ]
    return data


@pytest.mark.parametrize(
    "name,days", [("Hoje", 1), ("Últimos 7 dias", 7), ("Últimos 30 dias", 30), ("Últimos 90 dias", 90)]
)
def test_period_presets(name, days):
    start, end = period(name, date(2026, 9, 30))
    assert (end - start).days + 1 == days


def test_year_and_custom_period():
    assert period("Ano atual", date(2026, 9, 30)) == (date(2026, 1, 1), date(2026, 9, 30))
    assert period("Personalizado", date(2026, 9, 30), (date(2026, 2, 1), date(2026, 2, 2))) == (
        date(2026, 2, 1),
        date(2026, 2, 2),
    )


@pytest.mark.parametrize(
    "dates", [(), (date(2026, 9, 3),), (date(2026, 9, 3), date(2026, 9, 1)), (date(2026, 9, 1), date(2026, 10, 1))]
)
def test_invalid_period(dates):
    with pytest.raises(ValueError):
        period("Personalizado", date(2026, 9, 30), dates)


def test_local_day_utc_boundary_and_invalid_timestamps():
    start, end = bounds(date(2026, 9, 1), date(2026, 9, 1))
    assert start.hour == 3 and (end - start).days == 1
    assert inside("2026-09-02T02:59:59+00:00", start, end)
    assert not inside("2026-09-02T03:00:00+00:00", start, end)
    assert not inside("now", start, end)
    assert stamp("2026-09-01T00:00:00") is None


def test_new_ads_are_not_new_identities_or_human_absences(evidence):
    result = report(evidence)
    assert result["metrics"]["Novos anúncios"] == 2
    assert result["metrics"]["Possíveis novas identidades"] == 1
    assert result["metrics"]["Ausências confirmadas acumuladas"] == 0
    assert result["recurrence"][0]["Anúncios distintos"] == 2


def test_recollection_does_not_inflate_demand_or_history(evidence):
    evidence["coverage"] += deepcopy(evidence["coverage"])
    evidence["observations"] *= 3
    result = report(evidence)
    assert result["metrics"]["Novos anúncios"] == 2
    assert sum(r["Quantidade"] for r in result["coverage_series"]) == 2
    assert result["recurrence"][0]["Anúncios distintos"] == 2


def test_incomplete_identity_not_promoted_to_possible_new(evidence):
    evidence["ads"][0]["year"] = None
    evidence["ads"][1]["year"] = None
    assert report(evidence)["metrics"]["Possíveis novas identidades"] == 0


def test_exited_ad_counts_as_new_but_not_current_demand(evidence):
    evidence["ads"][0]["active_at_end"] = False
    result = report(evidence)
    assert len(result["stock"]) == 1 and result["metrics"]["Novos anúncios"] == 2


@pytest.mark.parametrize("field", FILTERS)
def test_filters_never_silently_ignore_missing_fields(field, evidence):
    result = report(evidence, {field: ["does-not-exist"]})
    assert not result["stock"]
    assert all(v == 0 for v in result["metrics"].values())
    assert accepts({field: 2025}, {field: ["2025"]})


def test_mean_median_and_empty_sample():
    assert duration_stats([]) == {"amostra": 0, "média em dias": None, "mediana em dias": None}
    assert duration_stats([1, 2, 9]) == {"amostra": 3, "média em dias": 4, "mediana em dias": 2}
    assert duration_stats([None, -3, 5])["amostra"] == 1


def test_stages_reentry_samples_and_open_age(evidence):
    evidence["development"] = [
        {"id": 1, "manufacturer": "BMW", "model": "F 900 R", "year": 2025, "created_at": instant(1)}
    ]
    evidence["origins"] = [{"item_id": 1, "external_id": "1"}] * 2
    evidence["development_events"] = [
        {"id": i, "item_id": 1, "created_at": instant(day), "after": {"status": state, "assigned_to": "Equipe"}}
        for i, (day, state) in enumerate(
            [(1, "NEW"), (3, "IN_DEVELOPMENT"), (5, "IN_VALIDATION"), (8, "IN_DEVELOPMENT")], 1
        )
    ]
    result = report(evidence)
    assert result["metrics"]["Desenvolvimentos ativos"] == 1
    stage = next(r for r in result["stage_times"] if r["Etapa"] == "Em desenvolvimento")
    assert stage["amostra"] == 1 and stage["média em dias"] == 2
    assert len(result["overdue"]) == 1
    assert result["stalled"][0]["assigned_to"] == "Equipe"
    assert result["stalled"][0]["priority"] == "Não avaliada"


def test_alert_unique_origins_and_history_status(evidence):
    evidence["alerts"] = [
        {
            "id": 1,
            "key": source + ":1",
            "external_id": "1",
            "status": status,
            "severity": "ALTA",
            "created_at": instant(4),
        }
        for source, status in [("alerts", "NOVO"), ("development_alerts", "RESOLVIDO")]
    ]
    result = report(evidence)
    assert result["metrics"]["Novos alertas"] == 2
    assert result["metrics"]["Alertas relevantes"] == 1


def test_rates_empty_denominator_are_unavailable():
    result = report(empty())
    assert all(r["Percentual"] is None for r in result["rates"])


def test_human_absence_requires_revalidated_review(evidence):
    evidence["coverage"][0]["effective_result"] = matching("CONFIRMADO_AUSENTE_NA_BASE")
    assert report(evidence)["metrics"]["Ausências confirmadas acumuladas"] == 0


def test_old_identity_priority_not_reused(evidence):
    evidence["priorities"] = [
        {"entity_id": "1", "identity_key": signature(vehicle(model="OTHER")), "priority": "high", "manual": True}
    ]
    assert report(evidence)["stock"][0]["priority"] == "Não avaliada"


def test_manual_priority_and_automatic_matching_ratio(evidence):
    evidence["priorities"] = [
        {"entity_id": "1", "identity_key": signature(vehicle()), "priority": "high", "manual": True}
    ]
    evidence["coverage"][0]["matching"] = matching("EXATO_NORMALIZADO", "SUPORTADO")
    result = report(evidence)
    assert result["stock"][0]["manual_priority"]
    assert result["metrics"]["Cobertura conhecida"] == 1
    ratio = next(r for r in result["rates"] if r["Indicador"].startswith("Matching"))
    assert ratio["Percentual"] == 50


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "analytics.sqlite3"
    import_base(path, [motorcycle("F 900 R", status="SEM_SUPORTE")])
    coverage(path, [ad(model="NEW 1234")], tmp_path / "reports")
    return path


def dump(path):
    with sqlite3.connect(path) as db:
        return "\n".join(db.iterdump())


def test_repository_readonly_and_real_matching_rules(db):
    before_dump = dump(db)
    now = datetime.now(UTC) + timedelta(seconds=1)
    data = ManagementMetricsRepository(db).snapshot("wr_motos", now)
    assert len(data["reviews"]) == 1 and len(data["ads"]) == 1
    assert data["reviews"][0]["state"] == "pending"
    assert dump(db) == before_dump


def test_future_decision_excluded_and_new_base_invalidates_absence(db):
    repo = ManagementMetricsRepository(db)
    cutoff = datetime.now(UTC)
    with ReviewRepository(db) as r:
        item = r.list_items()[0]
        r.decide(item["id"], "NAO_EXISTE_NA_BASE", "Fixture", "Conferido", None)
    old = repo.snapshot("wr_motos", cutoff)
    assert old["reviews"][0]["human_decision"] is None
    current = repo.snapshot("wr_motos", datetime.now(UTC) + timedelta(seconds=1))
    assert current["reviews"][0]["effective"]["match_type"] == "CONFIRMADO_AUSENTE_NA_BASE"
    import_base(db, [motorcycle("ANOTHER", status="SEM_SUPORTE")])
    latest = repo.snapshot("wr_motos", datetime.now(UTC) + timedelta(seconds=1))
    assert latest["reviews"][0]["stale_reason"] == "STALE_BASE_VERSION"
    previous = repo.snapshot("wr_motos", datetime.now(UTC) + timedelta(seconds=1), version=1)
    assert previous["reviews"][0]["effective"]["match_type"] == "CONFIRMADO_AUSENTE_NA_BASE"


def test_unpublished_version_unavailable(db):
    data = ManagementMetricsRepository(db).snapshot("wr_motos", datetime.now(UTC) + timedelta(seconds=1), 999)
    assert data["base_id"] is None and data["base"] == []


def test_cache_invalidation_and_copy_isolation(db):
    now = datetime.now(UTC) + timedelta(seconds=1)
    service = ManagementMetricsService(db, clock=lambda: now)
    start, end = date(2026, 9, 1), now.astimezone(__import__("zoneinfo").ZoneInfo("America/Sao_Paulo")).date()
    first = service.report(start, end)
    first["metrics"]["Novos anúncios"] = 999
    assert service.report(start, end)["metrics"]["Novos anúncios"] == 1
    with ReviewRepository(db) as r:
        r.decide(r.list_items()[0]["id"], "NAO_EXISTE_NA_BASE", "Fixture", "Conferido", None)
    second = service.report(start, end)
    assert second["metrics"]["Ausências confirmadas acumuladas"] == 1
    assert all(second["metrics"][name] == len(rows) for name, rows in second["details"].items())


def test_csv_definitions_filters_and_no_private_notes(db):
    now = datetime.now(UTC) + timedelta(seconds=1)
    service = ManagementMetricsService(db, clock=lambda: now)
    result = service.report(
        date(2026, 9, 1), now.astimezone(__import__("zoneinfo").ZoneInfo("America/Sao_Paulo")).date()
    )
    result["partner"] = '=HYPERLINK("bad")'
    content = csv_export(result).decode("utf-8-sig")
    records = list(csv.DictReader(io.StringIO(content), delimiter=";"))
    assert records[0]["parceiro"].startswith("'=")
    assert "Fixture justification" not in content
    assert records[0]["definicao"] and records[0]["corte_utc"]


def test_ui_has_no_sql_or_operational_commands():
    source = Path("ui/management_dashboard.py").read_text(encoding="utf-8")
    assert "SELECT " not in source and ".execute(" not in source
    assert ".refresh(" not in source and ".decide(" not in source


def test_management_ui_filters_dates_drilldown_and_readonly(db, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("MOTO_DB", str(db))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    before_dump = dump(db)
    ui = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    ui.radio(key="navigation").set_value("Indicadores gerenciais").run()
    assert not ui.exception and not ui.error
    ui.multiselect(key="management_manufacturer").set_value(["BMW"])
    next(b for b in ui.button if b.label == "Aplicar filtros").click().run()
    assert not ui.exception and not ui.error
    next(b for b in ui.button if b.key == "metric_Novos anúncios").click().run()
    assert ui.selectbox(key="management_detail").value == "Novos anúncios"
    next(s for s in ui.selectbox if s.label == "Período").set_value("Personalizado").run()
    assert len(ui.date_input) == 1
    ui.date_input[0].set_value((date(2026, 9, 1), date(2026, 9, 2))).run()
    assert not ui.exception and not ui.error
    assert ui.metric[0].value == "0"
    assert dump(db) == before_dump


def test_revalidation_required_excludes_preserved_decisions(db):
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE scanner_versions SET report_json=? WHERE import_id=1", ('{"review_affected":0}',))
        version = connection.execute("SELECT id FROM scanner_versions WHERE import_id=1").fetchone()[0]
        connection.execute(
            "INSERT INTO scanner_impacts(version_id,kind,entity_id,payload_json) VALUES (?,'REVIEW',1,?)",
            (version, '{"reason":"VALID"}'),
        )
    snapshot = ManagementMetricsRepository(db).snapshot("wr_motos", datetime.now(UTC) + timedelta(seconds=1))
    assert snapshot["version"]["revalidation_required"] == 0
