"""No external integration: the second adapter exists exclusively in this file."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest
from test_development import create
from test_matching import motorcycle
from test_review_queue import ad, import_base

from app.partners import main as partners_cli
from database.alert_repository import read_alerts
from database.partner_repository import PartnerRepository
from database.pipeline_repository import PipelineRepository, read_pipeline
from partners.base_partner import PartnerAdapter
from partners.config import PartnerLimits, PartnerSettings, load_settings, validate_key
from partners.models import CollectionResult
from partners.registry import PartnerRegistry
from partners.wr_motos import WRMotosCollector
from services import vehicle_images
from services.dashboard_service import DashboardConfig, DashboardService
from services.development_service import DevelopmentService
from services.partner_service import partner_status
from services.pipeline_lock import AlreadyRunning, ExecutionLock
from services.pipeline_service import run_pipeline
from services.scheduler_config import SchedulerConfig, utcnow
from services.scheduler_service import scheduler_status, serve
from services.vehicle_image_cache import digest, read_cached, write_cached
from services.vehicle_image_config import VehicleImageConfig


class FakePartnerAdapter(PartnerAdapter):
    partner_key = "fixture_partner"
    display_name = "Parceiro de teste"

    def collect_motorcycles(self):
        return CollectionResult(
            self.partner_key,
            utcnow().isoformat(),
            advertisements=[self.normalize_ad(ad(partner=self.partner_key))],
            complete=True,
        )


@pytest.fixture
def architecture(tmp_path):
    path = tmp_path / "architecture.sqlite3"
    import_base(path, [motorcycle(), motorcycle("F 900 R GT")])
    registry = PartnerRegistry(
        [*load_settings(), PartnerSettings("fixture_partner", "Parceiro de teste", "fixture")],
        {"wr_motos": WRMotosCollector, "fixture": FakePartnerAdapter},
    )
    config = SchedulerConfig(
        reports=str(tmp_path / "reports"), log_file=str(tmp_path / "pipeline.log"), retry_backoff_seconds=0
    )
    return path, registry, config


def publish(architecture, partner="fixture_partner", **kwargs):
    path, registry, config = architecture
    if partner == "wr_motos":

        class FixtureWR(WRMotosCollector):
            def collect_motorcycles(self):
                return CollectionResult("wr_motos", utcnow().isoformat(), advertisements=[ad()], complete=True)

        kwargs.setdefault("collector_factory", lambda *_: FixtureWR())
    return run_pipeline(path, config, partner_key=partner, registry=registry, **kwargs)


def test_production_registry_only_wr():
    registry = PartnerRegistry()
    assert [p.partner_key for p in registry.list(enabled_only=True)] == ["wr_motos"]
    adapter = registry.create("wr_motos")
    assert isinstance(adapter, PartnerAdapter)
    assert adapter.supports_images and adapter.supports_zero_km
    assert adapter.normalize_ad(ad(zero_km=None)).zero_km is None


def test_fake_contract_and_registry(architecture):
    _, registry, _ = architecture
    assert len(registry.list()) == 2
    adapter = registry.create("fixture_partner")
    assert adapter.collect().advertisements[0].normalized_key
    assert not adapter.supports_images and not adapter.supports_price
    with pytest.raises(ValueError, match="duplicado"):
        registry.register(registry.get("fixture_partner"))


@pytest.mark.parametrize("key", ["", "../other", "WR", "a/b", "a.b", "a" * 65, None])
def test_invalid_keys(key):
    with pytest.raises(ValueError):
        validate_key(key)


@pytest.mark.parametrize(
    "limits",
    [
        {"retries": -1},
        {"timeout_seconds": 0},
        {"concurrency": True},
        {"delay_seconds": 0},
        {"max_pages": 0},
        {"retries": 2.2},
    ],
)
def test_invalid_limits(limits):
    with pytest.raises(ValueError):
        PartnerLimits(**limits)


def test_config_rejects_duplicate_and_unknown(tmp_path):
    path = tmp_path / "partners.json"
    path.write_text('{"partners":{"wr_motos":{},"wr_motos":{}}}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicada"):
        load_settings(path)
    with pytest.raises(ValueError, match="desconhecido"):
        PartnerRegistry([PartnerSettings("unknown", "Unknown", "unknown")])
    with pytest.raises(ValueError, match="incompatível"):
        PartnerRegistry([replace(load_settings()[0], limits=PartnerLimits(concurrency=2))])


def test_disabled_partner_cannot_execute(architecture):
    path, registry, config = architecture
    disabled = PartnerRegistry(
        [replace(registry.get("fixture_partner"), enabled=False)], {"fixture": FakePartnerAdapter}
    )
    assert not disabled.list(enabled_only=True)
    with pytest.raises(ValueError, match="desabilitado"):
        run_pipeline(path, config, partner_key="fixture_partner", registry=disabled)
    assert not read_pipeline(path, partner="fixture_partner")["runs"]


def test_same_id_pipeline_persistence_review_alerts_history_isolated(architecture):
    path, registry, _ = architecture
    one = publish(architecture, "wr_motos", request_key="same")
    two = publish(architecture, request_key="same")
    assert one["status"] == two["status"] == "SUCCESS"
    assert one["id"] != two["id"]
    assert publish(architecture, request_key="same")["id"] == two["id"]
    assert two["summary"]["new"] == one["summary"]["new"] == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT partner,external_id FROM partner_advertisements ORDER BY partner").fetchall() == [
            ("fixture_partner", "1"),
            ("wr_motos", "1"),
        ]
        assert db.execute("SELECT count(DISTINCT partner) FROM review_items").fetchone()[0] == 2
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    for partner, run in [("wr_motos", one), ("fixture_partner", two)]:
        assert [r["id"] for r in read_pipeline(path, partner=partner)["runs"]] == [run["id"]]
        assert all(a["partner"] == partner for a in read_alerts(path, partner)["alerts"])
        dashboard = DashboardService(DashboardConfig(path, partner=partner))
        assert {a["partner"] for a in dashboard.snapshot()["stock"]} == {partner}
        assert {q["partner"] for q in dashboard.snapshot()["queue"]} == {partner}
    keys = [a["deduplication_key"] for a in read_alerts(path)["alerts"]]
    assert len(keys) == len(set(keys))
    assert {r["partner"]: r["active_ads"] for r in partner_status(path, registry)} == {
        "wr_motos": 1,
        "fixture_partner": 1,
    }


def test_locks_and_recovery_are_per_partner(architecture):
    path, _, config = architecture
    with PipelineRepository(path) as repo:
        wr = repo.start("manual", config.digest)
        fake = repo.start("manual", config.digest, partner="fixture_partner")
    with ExecutionLock(path):
        with pytest.raises(AlreadyRunning), ExecutionLock(path):
            pass
        assert publish(architecture)["status"] == "SUCCESS"
    assert read_pipeline(path, run_id=wr)["runs"][0]["status"] == "RUNNING"
    assert read_pipeline(path, run_id=fake, partner="fixture_partner")["runs"][0]["status"] == "CANCELLED"
    with ExecutionLock(path, "scheduler"), ExecutionLock(path, "scheduler", partner="fixture_partner"):
        pass


def test_failure_does_not_change_other_stock_or_clear_alerts(architecture):
    path, _, _ = architecture
    publish(architecture, "wr_motos")
    publish(architecture)

    class Broken(FakePartnerAdapter):
        def collect_motorcycles(self):
            raise ValueError("fixture failure")

    failed = publish(architecture, collector_factory=lambda *_: Broken())
    assert failed["status"] == "FAILED" and failed["summary"]["disappeared"] is None
    failure_alerts = [a for a in read_alerts(path, "fixture_partner")["alerts"] if a["alert_type"] == "FALHA_PIPELINE"]
    assert len(failure_alerts) == 1
    assert publish(architecture, "wr_motos")["status"] == "SUCCESS"
    assert [
        a for a in read_alerts(path, "fixture_partner")["alerts"] if a["alert_type"] == "FALHA_PIPELINE"
    ] == failure_alerts
    assert all(r["active_ads"] == 1 for r in partner_status(path, architecture[1]))


def test_cross_partner_payload_rejected_before_persistence(architecture):
    path, _, _ = architecture
    with PartnerRepository(path) as repo, pytest.raises(ValueError, match="Origem"):
        repo.save_collection(CollectionResult("fixture_partner", "now", advertisements=[ad()], complete=True))
    assert not DashboardService(DashboardConfig(path)).snapshot()["stock"]


def test_development_preserves_multiple_origins_and_filters(architecture):
    path, _, _ = architecture
    import_base(path, [motorcycle()])
    publish(architecture, "wr_motos")
    publish(architecture)
    wr = DevelopmentService(DashboardConfig(path))
    fake = DevelopmentService(DashboardConfig(path, partner="fixture_partner"))
    item = create(wr)
    assert create(fake) == item
    assert {o["partner"] for o in wr.detail(item)["origins"]} == {"wr_motos", "fixture_partner"}
    assert wr.listing(filters={"partner": ["fixture_partner"]})["total"] == 1
    assert wr.listing(filters={"partner": ["missing"]})["metrics"]["active"] == 0


def test_scheduler_state_and_limits_isolated(architecture, tmp_path):
    path, registry, config = architecture
    from dataclasses import asdict

    settings = tmp_path / "scheduler.json"
    settings.write_text(json.dumps(asdict(config)), encoding="utf-8")
    serve(path, settings, max_ticks=1, partner_key="fixture_partner", registry=registry)
    assert read_pipeline(path)["scheduler"] is None
    assert (
        scheduler_status(path, config, partner_key="fixture_partner", registry=registry)["scheduler"]["partner"]
        == "fixture_partner"
    )
    limits = PartnerLimits(retries=0, timeout_seconds=9, delay_seconds=3)
    effective = limits.apply(config)
    assert effective.max_retries == 0 and effective.request_timeout_seconds == 9 and effective.delay_seconds == 3


def test_image_disk_memory_and_batch_isolation(tmp_path, monkeypatch):
    config = VehicleImageConfig()
    url = "https://www.wrmotos.com.br/photo.jpg"
    out = BytesIO()
    Image.new("RGB", (10, 10), "red").save(out, "JPEG")
    content = out.getvalue()
    assert digest(url, 140) == hashlib.sha256(f"v1|140|{url}".encode()).hexdigest()
    assert digest(url, 140) != digest(url, 140, "fixture_partner")
    write_cached(url, 140, content, config, tmp_path)
    assert read_cached(url, 140, config, tmp_path) == content
    assert read_cached(url, 140, config, tmp_path, partner="fixture_partner") is None
    calls = []

    def download(url, width, config, **kwargs):
        calls.append(kwargs.get("partner", "wr_motos"))
        return content

    monkeypatch.setattr(vehicle_images, "download_thumbnail", download)
    vehicle_images.clear_memory()
    assert vehicle_images.thumbnail(url, config, cache_dir=tmp_path, partner="fixture_partner") == content
    assert calls == ["fixture_partner"]
    rows = [
        {"partner": p, "primary_image_url": url, "state": "pending", "priority": "high"}
        for p in ["wr_motos", "fixture_partner"]
    ]
    resolved = []

    def resolve(row, *args, **kwargs):
        resolved.append(row["partner"])
        return vehicle_images.PhotoResult(content)

    monkeypatch.setattr(vehicle_images, "resolve_photo", resolve)
    vehicle_images.visible_photos(rows, config, cache_dir=tmp_path)
    assert set(resolved) == {"wr_motos", "fixture_partner"}
    vehicle_images.clear_memory()


@pytest.mark.parametrize("command", [["list"], ["show", "wr_motos"], ["status"]])
def test_partners_cli_is_read_only(command, tmp_path, capsys):
    database = tmp_path / "absent.sqlite3"
    assert partners_cli([*command, "--db", str(database)]) == 0
    assert "WR Motos" in capsys.readouterr().out
    assert not database.exists()


def test_registry_drives_dashboard_partner_page(architecture, monkeypatch):
    path, _, _ = architecture
    publish(architecture, "wr_motos")
    publish(architecture)
    monkeypatch.setenv("MOTO_DB", str(path))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    app = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    assert not app.exception
    assert app.sidebar.selectbox[0].options == ["WR Motos"]
    app.sidebar.radio[0].set_value("Parceiros").run()
    assert not app.exception and not app.error
    assert "WR Motos" in str(app.table[0].value)
    assert "fixture_partner" not in str(app.table[0].value)


def test_human_decision_does_not_cross_partner(architecture):
    path, _, _ = architecture
    publish(architecture, "wr_motos")
    publish(architecture)
    wr = DashboardService(DashboardConfig(path))
    fake = DashboardService(DashboardConfig(path, partner="fixture_partner"))
    wr_id = wr.snapshot()["queue"][0]["id"]
    fake_id = fake.snapshot()["queue"][0]["id"]
    item = wr.detail(wr_id)
    wr.submit(wr_id, "CONFIRMAR_MATCH", "Teste", "Identidade conferida", "BMW|F900R|2025", "decision", item["revision"])
    assert fake.detail(fake_id)["human_decision"] is None
    with pytest.raises(ValueError):
        fake.detail(wr_id)
    publish(architecture)
    assert fake.detail(fake_id)["human_decision"] is None


def test_configured_retry_and_timeout_reach_adapter(architecture):
    path, registry, config = architecture
    calls = []

    class RetryAdapter(FakePartnerAdapter):
        @classmethod
        def for_pipeline(cls, settings, effective, folder):
            calls.append((effective.max_retries, effective.request_timeout_seconds, effective.delay_seconds))
            return cls()

        def collect_motorcycles(self):
            if len(calls) == 1:
                raise TimeoutError("fixture transient")
            return super().collect_motorcycles()

    settings = replace(
        registry.get("fixture_partner"), limits=PartnerLimits(retries=1, timeout_seconds=7, delay_seconds=4)
    )
    registry = PartnerRegistry([settings], {"fixture": RetryAdapter})
    # Use the same transient exception class as the HTTP transport.
    import requests

    original = RetryAdapter.collect_motorcycles

    def transient_collect(self):
        try:
            return original(self)
        except TimeoutError as exc:
            raise requests.exceptions.Timeout(str(exc)) from exc

    RetryAdapter.collect_motorcycles = transient_collect
    result = run_pipeline(path, config, registry=registry, partner_key="fixture_partner", sleeper=lambda _: None)
    assert result["status"] == "PARTIAL_SUCCESS"
    assert calls == [(1, 7, 4), (1, 7, 4)]


def test_empty_catalog_fingerprints_are_partner_specific(architecture):
    from services.pipeline_service import fingerprint

    path, _, _ = architecture
    with PipelineRepository(path) as repo:
        assert fingerprint(CollectionResult("wr_motos", "now"), repo) != fingerprint(
            CollectionResult("fixture_partner", "now"), repo
        )


def test_legacy_request_and_scheduler_migration_preserves_rows(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    # A genuine pre-12 database, not a drop/recreate of production tables.
    with sqlite3.connect(path) as db:
        for migration in sorted(Path("database/migrations").glob("*.sql")):
            if int(migration.name[:3]) < 12:
                db.executescript(migration.read_text(encoding="utf-8"))
                db.execute(
                    "INSERT OR IGNORE INTO schema_version(version) VALUES (?)",
                    (int(migration.name[:3]),),
                )
        db.execute(
            "INSERT INTO pipeline_runs(request_key,started_at,heartbeat_at,trigger_type,status,config_hash) VALUES ('old','now','now','manual','SUCCESS','hash')"
        )
        db.execute("INSERT INTO scheduler_state VALUES (1,'now',NULL,'hash','STOPPED')")
    assert read_pipeline(path)["runs"][0]["partner"] == "wr_motos"
    assert not read_pipeline(path, partner="fixture_partner")["runs"]
    with PipelineRepository(path) as repo:
        assert repo.existing("old") == 1
        second = repo.start("manual", "hash", "old", partner="fixture_partner")
        assert repo.existing("old", "fixture_partner") == second
        assert repo.connection.execute("SELECT request_key FROM pipeline_runs WHERE id=1").fetchone()[0] == "old"
    assert read_pipeline(path)["scheduler"]["partner"] == "wr_motos"


def test_fresh_streamlit_import_does_not_shadow_partners_package():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; sys.path.insert(0, str(Path('app').resolve())); import app.dashboard; import partners.registry; print('IMPORT_OK')",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK" in result.stdout


def test_alert_delivery_failure_allows_other_partner(architecture, monkeypatch):
    from database.alert_repository import AlertRepository

    original = AlertRepository.observe

    def broken(self, event, run, token):
        if event["partner"] == "fixture_partner":
            raise ValueError("fixture delivery unavailable")
        return original(self, event, run, token)

    monkeypatch.setattr(AlertRepository, "observe", broken)
    path, _, _ = architecture
    assert publish(architecture)["status"] == "SUCCESS"
    assert read_alerts(path, "fixture_partner")["pending"] == 1
    assert publish(architecture, "wr_motos")["status"] == "SUCCESS"
    assert read_alerts(path, "wr_motos")["pending"] == 0
    assert read_alerts(path, "wr_motos")["alerts"]
    assert read_alerts(path, "fixture_partner")["pending"] == 1


def test_development_photo_keeps_origin_when_filter_changes(architecture):
    path, _, _ = architecture
    import_base(path, [motorcycle()])
    publish(architecture, "wr_motos")

    class PhotoAdapter(FakePartnerAdapter):
        def collect_motorcycles(self):
            result = super().collect_motorcycles()
            result.advertisements[0].primary_image_url = "https://example.test/fixture.jpg"
            result.advertisements[0].collected_at = "2026-09-28T12:00:00+00:00"
            return result

    publish(architecture, collector_factory=lambda *_: PhotoAdapter())
    wr = DevelopmentService(DashboardConfig(path))
    fake = DevelopmentService(DashboardConfig(path, partner="fixture_partner"))
    item = create(wr)
    assert create(fake) == item
    listing = wr.listing(filters={"partner": ["wr_motos"]})
    assert listing["items"][0]["partner"] == "fixture_partner"
    assert listing["items"][0]["primary_image_url"] == "https://example.test/fixture.jpg"
