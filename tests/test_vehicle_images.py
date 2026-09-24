import json
import sqlite3
from dataclasses import asdict, replace
from io import BytesIO
from pathlib import Path

import pytest
import requests
from bs4 import BeautifulSoup
from PIL import Image
from streamlit.testing.v1 import AppTest
from test_matching import motorcycle
from test_partners import FIXTURES, STAMP, FixtureSource, card, parse
from test_pipeline import result, run
from test_pipeline import setup as pipeline_fixture
from test_review_queue import ad, collect, import_base

from database.partner_repository import PartnerRepository
from database.vehicle_images import latest_vehicle_image
from matching.review_policy import signature
from partners.images import IMAGE_FIELDS, extract_detail_image, extract_image, image_url
from partners.wr_http import WRHTTPSource
from partners.wr_motos import WRMotosCollector
from services.dashboard_service import DashboardConfig, DashboardService
from services.vehicle_image_config import VehicleImageConfig, load_image_config, should_show_vehicle_image
from services.vehicle_images import _thumbnail, download_thumbnail, safe_download_url, thumbnail, visible_thumbnails

PHOTO = "https://media.integradordeanuncios.com.br/media/fotos/329/1.jpg"
CONFIG = VehicleImageConfig()


@pytest.fixture
def setup(tmp_path):
    return pipeline_fixture.__wrapped__(tmp_path)


@pytest.fixture(autouse=True)
def clean_cache():
    _thumbnail.cache_clear()
    yield
    _thumbnail.cache_clear()


@pytest.mark.parametrize("attribute", ["src", "data-src", "data-lazy-src", "srcset", "data-srcset"])
def test_attributes(attribute):
    root = BeautifulSoup(f'<img {attribute}="/uploads/moto.jpg">', "html.parser")
    assert (
        extract_image(root, "https://www.wrmotos.com.br/v1/estoque/")[0]
        == "https://www.wrmotos.com.br/uploads/moto.jpg"
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        (PHOTO, PHOTO),
        ("//www.wrmotos.com.br/a.jpg", "https://www.wrmotos.com.br/a.jpg"),
        ("moto.jpg", "https://www.wrmotos.com.br/v1/estoque/moto.jpg"),
        ("file:///tmp/x", None),
        ("javascript:alert(1)", None),
        ("data:image/png;base64,x", None),
        ("https://u:p@www.wrmotos.com.br/a.jpg", None),
        ("https://[invalid/x", None),
        ("", None),
    ],
)
def test_urls(raw, expected):
    assert image_url(raw, "https://www.wrmotos.com.br/v1/estoque/") == expected


@pytest.mark.parametrize(
    "name", ["logo.png", "loading.gif", "sem-foto.jpg", "placeholder.png", "no_image.jpg", "wrmotos-1x.png"]
)
def test_placeholders(name):
    root = BeautifulSoup(f'<img src="/{name}">', "html.parser")
    assert extract_image(root, "https://www.wrmotos.com.br/") == (None, 1)


def test_priority_background_and_srcset():
    root = BeautifulSoup(
        '<img src="/placeholder.png" data-src="/real.jpg" srcset="/huge.jpg 900w, /small.jpg 140w">', "html.parser"
    )
    assert extract_image(root, "https://www.wrmotos.com.br/")[0].endswith("/real.jpg")
    root.img.attrs.pop("data-src")
    assert extract_image(root, "https://www.wrmotos.com.br/")[0].endswith("/small.jpg")
    root = BeautifulSoup("<div style=\"background-image:url('/moto.jpg')\"></div>", "html.parser")
    assert extract_image(root, "https://www.wrmotos.com.br/")[0].endswith("/moto.jpg")


def test_listing_fixture_and_absence_do_not_change_parsing():
    ads, errors, count = parse((FIXTURES / "listing-images.html").read_text())
    assert count == 3 and not errors
    assert ads[0].primary_image_url.endswith("/uploads/1.jpg")
    assert ads[1].primary_image_url.endswith("/uploads/2-small.jpg")
    assert ads[2].primary_image_url is None and not ads[2].parse_warnings
    before = parse(card())[0][0]
    after = parse(card().replace("</a>", '<img src="/moto.jpg"></a>'))[0][0]
    for field in ("manufacturer", "model", "year", "normalized_key", "parse_warnings", "raw_text"):
        assert getattr(before, field) == getattr(after, field)


def test_real_listing_and_individual_fixture():
    ads, _, _ = parse((FIXTURES / "page1.html").read_text(encoding="utf-8"))
    assert ads[0].image_source == "listing" and ads[0].image_last_seen_at == STAMP
    photo, rejected = extract_detail_image(
        (FIXTURES / "detail-image.html").read_text(), "https://www.wrmotos.com.br/v1/veiculo/?veiculo=446236"
    )
    assert "/446236-bmw.webp" in photo and rejected == 0
    assert extract_detail_image('<img src="/related.jpg">', "https://www.wrmotos.com.br/")[0] is None
    assert extract_detail_image('<meta property="og:image" content="/moto.jpg">', "https://www.wrmotos.com.br/")[
        0
    ].endswith("/moto.jpg")


def test_collector_image_failure_does_not_fail_collection():
    source = FixtureSource([card()])

    def broken(*args):
        raise requests.Timeout()

    source.fill_missing_images = broken
    r = WRMotosCollector(source).collect_motorcycles()
    assert r.complete and not r.errors and r.metadata["images"]["detail_failures"] == 1


def test_persistence_updates_retains_history_and_protects_identity(tmp_path):
    path = tmp_path / "db.sqlite3"
    a = ad(primary_image_url=PHOTO, image_source="listing", image_last_seen_at=STAMP)
    first = collect(path, [a])
    changed = replace(
        a,
        primary_image_url=PHOTO + "?v=2",
        collected_at="2026-09-23T00:00:00+00:00",
        image_last_seen_at="2026-09-23T00:00:00+00:00",
    )
    collect(path, [changed])
    collect(path, [replace(changed, primary_image_url=None, collected_at="2026-09-24T00:00:00+00:00")])
    with PartnerRepository(path) as repo:
        assert repo.get_collection(first).advertisements[0].primary_image_url == PHOTO
        assert latest_vehicle_image(repo.connection, asdict(a))["primary_image_url"] == PHOTO + "?v=2"
        assert repo.connection.execute("SELECT count(*) FROM partner_advertisements").fetchone()[0] == 1
        assert repo.connection.execute("SELECT count(*) FROM partner_vehicle_image_history").fetchone()[0] == 2
        assert repo.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    other = replace(a, model="OUTRA MOTO", primary_image_url=None, collected_at="2026-09-25T00:00:00+00:00")
    collect(path, [other])
    with PartnerRepository(path) as repo:
        assert latest_vehicle_image(repo.connection, asdict(other))["primary_image_url"] is None


def test_only_photo_changes_reuse_matching_and_keep_decisions_alerts(setup):
    a = ad(model="NOVA MOTO", primary_image_url=PHOTO, image_source="listing", image_last_seen_at=STAMP)
    first = run(setup, result([a]))
    service = DashboardService(DashboardConfig(setup[0]))
    before = service.detail(1)
    with sqlite3.connect(setup[0]) as db:
        counts = {
            table: db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in [
                "matching_runs",
                "review_items",
                "review_decisions",
                "review_occurrences",
                "alerts",
                "alert_occurrences",
            ]
        }
    second = run(setup, result([replace(a, primary_image_url=PHOTO + "?v=2")]))
    assert second["summary"]["reused"]
    after = service.detail(1)
    for key in ["automatic", "effective", "priority", "identity", "revision", "state", "history"]:
        assert before[key] == after[key]
    assert signature(asdict(a)) == signature(asdict(replace(a, primary_image_url=None)))
    assert after["advertisement"]["primary_image_url"].endswith("?v=2")
    assert first["summary"]["matching_counts"] == second["summary"]["matching_counts"]
    with sqlite3.connect(setup[0]) as db:
        assert counts == {t: db.execute("SELECT count(*) FROM " + t).fetchone()[0] for t in counts}


@pytest.mark.parametrize(
    "row,expected",
    [
        ({"effective_type": "NAO_ENCONTRADA_NA_BASE"}, True),
        ({"effective_type": "CONFIRMADO_AUSENTE_NA_BASE"}, True),
        ({"evidence": "Provável ausência"}, True),
        ({"priority": "high", "state": "pending"}, True),
        ({"priority": "high", "state": "invalidated"}, True),
        ({"priority": "high", "state": "resolved"}, False),
        ({"effective_type": "EXATO_NORMALIZADO", "coverage": "SUPORTADO"}, False),
    ],
)
def test_display_rules(row, expected):
    assert should_show_vehicle_image(row, CONFIG) is expected
    assert not should_show_vehicle_image(row, replace(CONFIG, enabled=False))


@pytest.mark.parametrize("alert_type", ["NOVO_ANUNCIO", "POSSIVEL_NOVA_MOTO", "REVISAO_ALTA_PRIORIDADE"])
def test_alert_photos(alert_type):
    assert should_show_vehicle_image({}, CONFIG, alert_type=alert_type)
    assert not should_show_vehicle_image({"coverage": "SUPORTADO"}, CONFIG, alert_type="NOVO_ANUNCIO")


@pytest.mark.parametrize(
    "key",
    [
        "enabled",
        "show_for_not_found",
        "show_for_probable_missing",
        "show_for_confirmed_missing",
        "show_for_high_priority_review",
    ],
)
def test_configuration_switches(key):
    rows = {
        "enabled": {},
        "show_for_not_found": {"effective_type": "NAO_ENCONTRADA_NA_BASE"},
        "show_for_probable_missing": {"evidence": "reason"},
        "show_for_confirmed_missing": {"effective_type": "CONFIRMADO_AUSENTE_NA_BASE"},
        "show_for_high_priority_review": {"priority": "high", "state": "pending"},
    }
    assert not should_show_vehicle_image(rows[key], replace(CONFIG, **{key: False}))


def test_invalid_config_disables_images(tmp_path):
    p = tmp_path / "images.json"
    p.write_text('{"enabled":"yes"}')
    assert not load_image_config(p).enabled


def jpeg():
    out = BytesIO()
    Image.new("RGB", (800, 450), "blue").save(out, "JPEG")
    return out.getvalue()


class Response:
    def __init__(self, body=None, status=200, headers=None):
        self.body = jpeg() if body is None else body
        self.status_code = status
        self.headers = headers or {"Content-Type": "image/jpeg"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield self.body


def network(monkeypatch, responses):
    from services import vehicle_images

    monkeypatch.setattr(vehicle_images, "safe_download_url", lambda url: None)

    def get(*args, **kwargs):
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(requests.Session, "get", get)


@pytest.mark.parametrize(
    "failure", ["timeout", "tls", "404", "html", "invalid", "size_header", "size_stream", "redirects"]
)
def test_download_failures_fallback(monkeypatch, tmp_path, failure):
    responses = {
        "timeout": [requests.Timeout()],
        "tls": [requests.exceptions.SSLError()],
        "404": [Response(status=404)],
        "html": [Response(headers={"Content-Type": "text/html"})],
        "invalid": [Response(body=b"not a photo")],
        "size_header": [Response(headers={"Content-Type": "image/jpeg", "Content-Length": "999999999"})],
        "size_stream": [Response(body=b"x" * 1025)],
        "redirects": [Response(status=302, headers={"Location": PHOTO}) for _ in range(3)],
    }[failure]
    network(monkeypatch, responses)
    config = replace(CONFIG, max_image_bytes=1024) if failure == "size_stream" else CONFIG
    assert thumbnail(PHOTO, config, cache_dir=tmp_path) is None
    assert thumbnail(PHOTO, config, cache_dir=tmp_path) is None
    assert not list(tmp_path.glob("*.jpg"))


def test_cache_resize_hash_and_no_original(monkeypatch, tmp_path):
    responses = [Response()]
    network(monkeypatch, responses)
    first = thumbnail(PHOTO, CONFIG, cache_dir=tmp_path)
    assert first
    with Image.open(BytesIO(first)) as image:
        assert image.size == (140, 79)
    file = next(tmp_path.glob("*.jpg"))
    assert len(file.stem) == 64
    _thumbnail.cache_clear()
    assert thumbnail(PHOTO, CONFIG, cache_dir=tmp_path) == first
    assert not responses


def test_no_disk_cache_and_disabled_download(monkeypatch, tmp_path):
    network(monkeypatch, [Response()])
    assert thumbnail(PHOTO, replace(CONFIG, cache_enabled=False), cache_dir=tmp_path)
    assert not list(tmp_path.iterdir())
    assert thumbnail(PHOTO, replace(CONFIG, enabled=False), cache_dir=tmp_path) is None


@pytest.mark.parametrize(
    "url",
    [
        "file:///a",
        "http://127.0.0.1/a.jpg",
        "https://evil.test/a.jpg",
        "https://www.wrmotos.com.br:8080/a.jpg",
        "https://www.wrmotos.com.br@evil.test/a.jpg",
    ],
)
def test_download_origin_allowlist(url):
    with pytest.raises(ValueError):
        safe_download_url(url)


def test_private_dns_and_redirect_blocked(monkeypatch):
    from services import vehicle_images

    monkeypatch.setattr(vehicle_images.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("127.0.0.1", 0))])
    with pytest.raises(ValueError):
        safe_download_url(PHOTO)
    monkeypatch.setattr(vehicle_images.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("8.8.8.8", 0))])
    monkeypatch.setattr(
        requests.Session, "get", lambda *a, **k: Response(status=302, headers={"Location": "http://127.0.0.1/a.jpg"})
    )
    with pytest.raises(ValueError):
        download_thumbnail(PHOTO, 140, CONFIG)


def test_load_only_visible_relevant_and_deduplicate(monkeypatch):
    from services import vehicle_images

    seen = []
    monkeypatch.setattr(vehicle_images, "thumbnail", lambda url, *a: seen.append(url) or b"photo")
    rows = [{"primary_image_url": PHOTO, "effective_type": "NAO_ENCONTRADA_NA_BASE"} for _ in range(20)]
    rows[0] = {"primary_image_url": PHOTO + "supported", "coverage": "SUPORTADO"}
    assert visible_thumbnails(rows, CONFIG) == {PHOTO: b"photo"} and seen == [PHOTO]


def test_detail_fallback_only_missing_and_failure_isolated(monkeypatch):
    from partners import wr_http

    monkeypatch.setattr(wr_http, "robots_policy", lambda *a, **k: {"delay": 2})
    monkeypatch.setattr(wr_http.time, "sleep", lambda *a: None)
    html = (FIXTURES / "detail-image.html").read_bytes()
    calls = []

    def get(self, url, **kwargs):
        calls.append(url)
        return Response(body=html) if len(calls) == 1 else Response(status=404)

    monkeypatch.setattr(requests.Session, "get", get)
    ads = [ad(primary_image_url=PHOTO), ad(external_id="2"), ad(external_id="3")]
    stats = WRHTTPSource().fill_missing_images(ads, CONFIG)
    assert len(calls) == 2 and all("veiculo=1" not in u for u in calls)
    assert ads[1].image_source == "detail" and not ads[2].primary_image_url
    assert stats["detail_failures"] == 1 and stats["detail_attempts"] == 2


def test_dashboard_images_readonly_pagination_alerts_and_fallback(setup, monkeypatch):
    from database.alert_repository import read_alerts
    from services import vehicle_images

    monkeypatch.setattr(vehicle_images, "thumbnail", lambda url, *a, **k: jpeg() if url else None)
    monkeypatch.setattr("ui.vehicle_images.thumbnail", lambda url, *a, **k: jpeg() if url else None)
    ads = [ad(external_id=str(i), model="NOVA MOTO", primary_image_url=PHOTO if i else None) for i in range(12)]
    run(setup, result(ads))
    monkeypatch.setenv("MOTO_DB", str(setup[0]))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    with sqlite3.connect(setup[0]) as db:
        before = list(db.iterdump())
    ui = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    ui.radio(key="navigation").set_value("Possíveis novas motos").run()
    assert not ui.exception and any("Foto" in t.value for t in ui.table)
    assert any("Foto não disponível" in t.value.to_string() for t in ui.table)
    assert all(len(t.value) <= 8 for t in ui.table)
    ui.radio(key="navigation").set_value("Fila de revisão").run()
    ui.selectbox(key="review_selection").set_value(2).run()
    assert not ui.exception and not any(b.label == "Salvar decisão" for b in ui.button)
    ui.radio(key="navigation").set_value("Alertas").run()
    alert = next(
        a
        for a in read_alerts(setup[0])["alerts"]
        if a["external_id"] == "1" and a["alert_type"] == "POSSIVEL_NOVA_MOTO"
    )
    ui.selectbox(key="alert_selection").set_value(alert["id"]).run()
    assert not ui.exception and not ui.error
    assert next(b for b in ui.button if b.label == "Marcar como lido").disabled
    with sqlite3.connect(setup[0]) as db:
        assert list(db.iterdump()) == before


def test_old_database_and_old_payload_compatibility(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        for migration in sorted(Path("database/migrations").glob("*.sql")):
            if migration.name.startswith("010"):
                break
            db.executescript(migration.read_text(encoding="utf-8"))
            db.execute("INSERT OR IGNORE INTO schema_version VALUES (?)", (int(migration.name[:3]),))
    with PartnerRepository(path) as repo:
        assert repo.connection.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 11
    import_base(path, [motorcycle()])
    cid = collect(path, [ad()])
    with sqlite3.connect(path) as db:
        payload = asdict(ad())
        for key in IMAGE_FIELDS:
            payload.pop(key)
        db.execute("UPDATE partner_observations SET payload_json=?", (json.dumps(payload),))
    with PartnerRepository(path) as repo:
        assert repo.get_collection(cid).advertisements[0].primary_image_url is None
