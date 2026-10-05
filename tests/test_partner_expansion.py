"""Milestone 8.1: no public-network calls; assessed candidates are not collectors."""

import json
from dataclasses import asdict, replace
from datetime import date
from threading import Event

import pytest
import test_partner_architecture as fixtures
from test_partner_architecture import publish
from test_review_queue import ad

from app.partners import main
from database.partner_repository import PartnerRepository
from partners.config import PartnerLimits, load_settings
from partners.models import CollectionResult
from partners.registry import PartnerRegistry
from services import management_metrics_service as metrics
from services.dashboard_service import DashboardConfig
from services.multi_partner_service import run_all
from services.partner_identity_service import cross_partner_opportunities, group_occurrences
from services.partner_service import partner_status
from services.scheduler_config import SchedulerConfig

architecture = fixtures.architecture


def row(partner="wr_motos", **changes):
    return {**asdict(ad(partner=partner)), "effective_type": "NAO_ENCONTRADA_NA_BASE", **changes}


def test_candidates_informational_only(tmp_path, capsys):
    assert main(["list"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["integration_status"] for r in rows] == ["Ativo", "Não integrado", "Não integrado", "Não integrado"]
    for key in ("moto_marques", "thomas_motos", "motonil"):
        assert main(["show", key]) == 0
        assert json.loads(capsys.readouterr().out)["enabled"] is False
        with pytest.raises(ValueError):
            PartnerRegistry().create(key)
    assert not (tmp_path / "absent.sqlite3").exists()


def test_strict_identity_multiple_origins():
    grouped = group_occurrences([row(), row("fixture_partner"), row()])
    assert len(grouped) == 1
    assert grouped[0]["partner_count"] == grouped[0]["occurrence_count"] == 2
    assert len(grouped[0]["origins"]) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"year": None},
        {"version": "GT"},
        {"effective_type": "AMBIGUOUS"},
        {"effective_type": "CORRESPONDENCIA_PROVAVEL"},
        {"effective_type": "AGUARDANDO_MATCHING"},
        {"parse_warnings": ["INVALID_YEAR"]},
        {"human_status": "Em dúvida"},
        {"model": "F 900 XR"},
    ],
)
def test_uncertain_or_distinct_identity_does_not_merge(change):
    assert len(group_occurrences([row(), row("fixture_partner", **change)])) == 2


def test_human_decisions_remain_per_origin():
    groups = group_occurrences(
        [
            row(human_status="Não existe na base", effective_type="CONFIRMADO_AUSENTE_NA_BASE"),
            row("fixture_partner", human_status="Sem decisão"),
        ]
    )
    assert len(groups) == 1
    assert {r["human_status"] for r in groups[0]["origins"]} == {"Não existe na base", "Sem decisão"}


def test_run_all_is_concurrent_and_isolates_exception(architecture):
    path, registry, config = architecture
    fast_done = Event()

    def runner(database, config, *, partner_key, **kwargs):
        if partner_key == "wr_motos":
            assert fast_done.wait(5), "Slow partner must not prevent the other from starting"
            raise TimeoutError("simulated")
        fast_done.set()
        return {"status": "SUCCESS"}

    results = run_all(path, config, registry=registry, runner=runner)
    assert results["wr_motos"]["status"] == "FAILED"
    assert results["fixture_partner"]["status"] == "SUCCESS"


def test_run_all_skips_disabled_and_preserves_request_key(architecture):
    path, registry, config = architecture
    registry._settings["wr_motos"] = replace(registry.get("wr_motos"), enabled=False)
    calls = []

    def runner(*args, **kwargs):
        calls.append(kwargs)
        return {"status": "SUCCESS"}

    assert list(run_all(path, config, registry=registry, runner=runner, request_key="batch")) == ["fixture_partner"]
    assert calls[0]["request_key"] == "batch"


def test_run_all_missing_database_is_not_created(tmp_path):
    path = tmp_path / "absent.sqlite3"
    with pytest.raises(ValueError, match="Banco"):
        run_all(path, SchedulerConfig())
    assert not path.exists()


@pytest.mark.parametrize("bad", [0, 31, True, float("nan")])
def test_rate_limit_invalid(bad):
    with pytest.raises(ValueError):
        PartnerLimits(requests_per_minute=bad)


def test_rate_limit_reaches_wr_transport(tmp_path):
    settings = replace(
        load_settings()[0], limits=PartnerLimits(requests_per_minute=5), detail_lookup=False, image_fetch=False
    )
    registry = PartnerRegistry([settings])
    effective = settings.limits.apply(SchedulerConfig())
    assert effective.delay_seconds == 12
    adapter = registry.for_pipeline("wr_motos", effective, tmp_path)
    assert not adapter.detail_lookup and not adapter.image_fetch
    assert adapter.supports_detail_lookup


def test_status_counts_new_returned_and_partial(architecture):
    path, registry, _ = architecture

    def save(ids, complete=True):
        with PartnerRepository(path) as repo:
            repo.save_collection(
                CollectionResult(
                    "wr_motos",
                    "2026-10-05T12:00:00+00:00",
                    advertisements=[ad(external_id=x) for x in ids],
                    complete=complete,
                    duration_seconds=1.25,
                )
            )
        return partner_status(path, registry)[0]

    assert save(["a", "b"])["new"] == 2
    assert save(["a"])["disappeared"] == 1
    returned = save(["a", "b"])
    assert returned["reappeared"] == 1 and returned["new"] == 0
    partial = save(["c"], False)
    assert partial["disappeared"] is None and partial["partial"]
    assert partial["active_ads"] == 3 and partial["duration_seconds"] == 1.25


def test_management_grouping_same_cut_and_no_global_identity_sum(monkeypatch):
    registry = PartnerRegistry()
    registry._settings["other"] = replace(registry.get("wr_motos"), partner_key="other", display_name="Outro")
    calls = []

    class Analytics:
        def __init__(self, path, partner, clock):
            self.partner = partner
            calls.append(clock())

        def report(self, *args, **kwargs):
            return {
                "stock": [row(self.partner, automatic_resolved=True, automatic_current=True)],
                "metrics": {
                    name: 1
                    for name in (
                        "Novos anúncios",
                        "Possíveis novas identidades",
                        "Revisões pendentes",
                        "Ausências confirmadas acumuladas",
                    )
                },
            }

    monkeypatch.setattr(metrics, "ManagementMetricsService", Analytics)
    result = metrics.reports_by_partner("unused", date(2026, 10, 1), date(2026, 10, 5), registry=registry)
    assert len(result["partners"]) == 2
    assert result["occurrences"] == 2 and result["identity_groups"] == 1
    assert calls[0] == calls[1]


def test_cross_partner_opportunities_read_only(architecture):
    path, registry, _ = architecture
    publish(architecture, "wr_motos")
    publish(architecture)
    before = path.read_bytes()
    groups = cross_partner_opportunities(DashboardConfig(path), registry)
    assert all(g["occurrence_count"] >= g["partner_count"] for g in groups)
    assert path.read_bytes() == before


def test_run_all_real_pipeline_with_fixtures_and_partner_locks(architecture, monkeypatch):
    from partners.wr_motos import WRMotosCollector
    from services.pipeline_lock import ExecutionLock

    path, registry, config = architecture
    monkeypatch.setattr(
        WRMotosCollector,
        "collect_motorcycles",
        lambda self: CollectionResult("wr_motos", "2026-10-05T12:00:00+00:00", advertisements=[ad()], complete=True),
    )
    with ExecutionLock(path, partner="wr_motos"):
        results = run_all(path, config, registry=registry, request_key="locked-batch")
    assert results["wr_motos"]["status"] == "SKIPPED_ALREADY_RUNNING"
    assert results["fixture_partner"]["status"] == "SUCCESS"
    results = run_all(path, config, registry=registry, request_key="full-batch")
    assert all(r["status"] == "SUCCESS" for r in results.values())
    repeated = run_all(path, config, registry=registry, request_key="full-batch")
    assert {p: r["id"] for p, r in repeated.items()} == {p: r["id"] for p, r in results.items()}
    assert all(r["active_ads"] == 1 for r in partner_status(path, registry))


def test_image_fetch_disabled_before_network(monkeypatch):
    from services.vehicle_images import safe_download_url

    registry = PartnerRegistry([replace(load_settings()[0], image_fetch=False)])
    monkeypatch.setattr("partners.registry.PartnerRegistry", lambda: registry)
    with pytest.raises(ValueError, match="desabilitada"):
        safe_download_url("https://www.wrmotos.com.br/photo.jpg")
