import json
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
import requests
from PIL import Image
from test_vehicle_images import CONFIG, PHOTO, Response, network

from services import vehicle_image_cache as disk
from services import vehicle_images as photos
from services.vehicle_image_config import VehicleImageConfig
from services.vehicle_image_metrics import metrics, reset_metrics
from ui.vehicle_images import photo_message, placeholder


def tiny():
    output = BytesIO()
    Image.new("RGB", (140, 80), "gray").save(output, "JPEG")
    return output.getvalue()


@pytest.fixture(autouse=True)
def reset():
    photos.clear_memory()
    reset_metrics()
    yield
    photos.clear_memory()


def stored(tmp_path, url=PHOTO, config=CONFIG):
    assert disk.write_cached(url, 140, tiny(), config, tmp_path)
    return tmp_path / (disk.digest(url, 140) + ".jpg")


def test_cache_miss_memory_hit_disk_hit(monkeypatch, tmp_path):
    network(monkeypatch, [Response()])
    first = photos.thumbnail(PHOTO, CONFIG, cache_dir=tmp_path)
    assert first
    assert photos.thumbnail(PHOTO, CONFIG, cache_dir=tmp_path) == first
    photos.clear_memory()
    assert photos.thumbnail(PHOTO, CONFIG, cache_dir=tmp_path) == first
    stats = metrics()
    assert stats["downloads"] == stats["cache_misses"] == stats["memory_hits"] == stats["disk_hits"] == 1


def test_expired_disk_image_is_not_used(monkeypatch, tmp_path):
    path = stored(tmp_path)
    os.utime(path, (time.time() - 73 * 3600,) * 2)
    assert disk.read_cached(PHOTO, 140, CONFIG, tmp_path) is None
    network(monkeypatch, [Response()])
    assert photos.thumbnail(PHOTO, CONFIG, cache_dir=tmp_path)
    assert metrics()["downloads"] == 1


def test_memory_and_negative_results_expire(monkeypatch, tmp_path):
    clock = [time.time()]
    monkeypatch.setattr(photos.time, "time", lambda: clock[0])
    network(monkeypatch, [requests.Timeout(), Response(), Response()])
    config = replace(CONFIG, cache_enabled=False, cache_ttl_hours=0.001, failure_retry_seconds=2)
    assert photos.thumbnail(PHOTO, config, cache_dir=tmp_path) is None
    assert photos.thumbnail(PHOTO, config, cache_dir=tmp_path) is None
    clock[0] += 3
    assert photos.thumbnail(PHOTO, config, cache_dir=tmp_path)
    clock[0] += 4
    assert photos.thumbnail(PHOTO, config, cache_dir=tmp_path)
    assert metrics()["downloads"] == 3 and metrics()["failures"] == 1


@pytest.mark.parametrize("content", [b"<html>error</html>", b"invalid", b"\xff\xd8\xffbroken"])
def test_corrupt_cache_recovers(monkeypatch, tmp_path, content):
    path = stored(tmp_path)
    path.write_bytes(content)
    network(monkeypatch, [Response()])
    assert photos.thumbnail(PHOTO, CONFIG, cache_dir=tmp_path)
    assert disk.valid_cached(path.read_bytes(), 140)


def test_truncated_jpeg_rejected(tmp_path):
    path = stored(tmp_path)
    path.write_bytes(path.read_bytes()[:-30])
    assert disk.read_cached(PHOTO, 140, CONFIG, tmp_path) is None
    assert not path.exists()


def test_cleanup_ttl_and_oldest_limit(tmp_path):
    config = replace(CONFIG, cache_max_mb=0.004)
    for i in range(4):
        path = tmp_path / (f"{i:064x}" + ".jpg")
        path.write_bytes(b"x" * 2000)
        os.utime(path, (time.time() - (1000 - i),) * 2)
    expired = tmp_path / ("f" * 64 + ".jpg")
    expired.write_bytes(b"x")
    os.utime(expired, (time.time() - 74 * 3600,) * 2)
    result = disk.cleanup_cache(tmp_path, config)
    assert result["removed"] == 3 and result["bytes"] == 4000
    assert sorted(p.stem for p in tmp_path.glob("*.jpg")) == [f"{i:064x}" for i in (2, 3)]


def test_quota_after_concurrent_writes(tmp_path):
    config = replace(CONFIG, cache_max_mb=0.004)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: disk.write_cached(PHOTO + str(i), 140, tiny(), config, tmp_path), range(20)))
    assert sum(p.stat().st_size for p in tmp_path.glob("*.jpg")) <= int(config.cache_max_mb * 1024 * 1024)
    assert not list(tmp_path.glob("*.tmp"))


def test_cleanup_never_deletes_foreign_or_nested_files(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    outside = tmp_path / ("e" * 64 + ".jpg")
    outside.write_bytes(b"outside")
    (cache / "user.jpg").write_bytes(b"foreign")
    nested = cache / "nested"
    nested.mkdir()
    (nested / ("f" * 64 + ".jpg")).write_bytes(b"nested")
    disk.cleanup_cache(cache, replace(CONFIG, cache_max_mb=0.001))
    assert outside.read_bytes() == b"outside"
    assert (cache / "user.jpg").read_bytes() == b"foreign"
    assert (nested / ("f" * 64 + ".jpg")).exists()


def test_symlink_entry_ignored_without_following(monkeypatch, tmp_path):
    path = stored(tmp_path)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == path or original(p))
    os.utime(path, (time.time() - 74 * 3600,) * 2)
    disk.cleanup_cache(tmp_path, CONFIG)
    assert path.exists()
    assert disk.read_cached(PHOTO, 140, CONFIG, tmp_path) is None
    assert not disk.write_cached(PHOTO, 140, tiny(), CONFIG, tmp_path)


def test_linked_root_rejected(monkeypatch, tmp_path):
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda p: p == tmp_path or original(p))
    assert disk.cleanup_cache(tmp_path, CONFIG)["error"] == "ValueError"
    assert not disk.write_cached(PHOTO, 140, tiny(), CONFIG, tmp_path)
    assert not list(tmp_path.iterdir())


def test_cleanup_failure_does_not_prevent_render(monkeypatch, tmp_path):
    original = Path.unlink
    path = stored(tmp_path)
    os.utime(path, (time.time() - 74 * 3600,) * 2)

    def denied(p, *args, **kwargs):
        if p == path:
            raise PermissionError("fixture")
        return original(p, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied)
    network(monkeypatch, [Response()])
    output = photos.visible_photos(
        [{"primary_image_url": PHOTO, "priority": "high", "state": "pending"}], CONFIG, cache_dir=tmp_path
    )
    assert output[0].content


def test_temporary_cleanup_and_no_partial_cache(monkeypatch, tmp_path):
    old = tmp_path / ("a" * 64 + "." + "b" * 32 + ".tmp")
    old.write_bytes(b"partial")
    os.utime(old, (time.time() - 120,) * 2)
    disk.cleanup_cache(tmp_path, CONFIG)
    assert not old.exists()
    monkeypatch.setattr(Path, "replace", lambda *a: (_ for _ in ()).throw(OSError("fixture")))
    assert not disk.write_cached(PHOTO, 140, tiny(), CONFIG, tmp_path)
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("format_name", ["JPEG", "PNG", "WEBP"])
def test_magic_bytes_and_decoder(format_name, monkeypatch):
    content = BytesIO()
    Image.new("RGB", (120, 80)).save(content, format_name)
    assert photos.raster_format(content.getvalue()) == format_name
    network(monkeypatch, [Response(body=content.getvalue(), headers={"Content-Type": "image/" + format_name.lower()})])
    assert photos.download_thumbnail(PHOTO, 140, CONFIG).startswith(b"\xff\xd8\xff")


@pytest.mark.parametrize(
    "body", [b"<html>login</html>", b"GIF89a" + b"x" * 50, b"RIFFxxxxNOTPdata", b"\xff\xd8\xffbroken"]
)
def test_spoofed_content_type_is_not_image(body, monkeypatch, tmp_path):
    network(monkeypatch, [Response(body=body, headers={"Content-Type": "image/jpeg"})])
    assert photos.thumbnail(PHOTO, CONFIG, cache_dir=tmp_path) is None
    assert not list(tmp_path.glob("*.jpg"))


def test_same_url_concurrent_calls_download_once(monkeypatch, tmp_path):
    calls = []

    def download(*args):
        calls.append(1)
        time.sleep(0.03)
        return tiny()

    monkeypatch.setattr(photos, "download_thumbnail", download)
    with ThreadPoolExecutor(max_workers=8) as pool:
        output = list(pool.map(lambda _: photos.thumbnail(PHOTO, CONFIG, cache_dir=tmp_path), range(8)))
    assert all(output) and len(calls) == 1


def test_visible_only_relevant_eight_and_concurrency_limit(monkeypatch, tmp_path):
    active = 0
    peak = 0
    urls = []
    lock = threading.Lock()

    def download(url, *args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            urls.append(url)
        time.sleep(0.03)
        with lock:
            active -= 1
        return tiny()

    monkeypatch.setattr(photos, "download_thumbnail", download)
    rows = [{"primary_image_url": PHOTO + str(i), "priority": "high", "state": "pending"} for i in range(20)]
    rows[0]["priority"] = "medium"
    result = photos.visible_photos(rows, replace(CONFIG, max_concurrent_downloads=2), cache_dir=tmp_path)
    assert len(result) == 8 and len(urls) == 7 and peak <= 2
    assert PHOTO + "8" not in urls and PHOTO + "0" not in urls


def test_missing_and_failed_are_distinct(monkeypatch, tmp_path):
    network(monkeypatch, [requests.Timeout()])
    missing = photos.resolve_photo({}, CONFIG, cache_dir=tmp_path)
    failure = photos.resolve_photo({"primary_image_url": PHOTO}, CONFIG, cache_dir=tmp_path)
    assert photo_message(missing) == "Foto não disponível"
    assert photo_message(failure) == "Não foi possível carregar a foto"
    assert metrics()["downloads"] == 1
    with Image.open(BytesIO(placeholder())) as image:
        assert image.size == (140, 88)


def test_known_listing_then_known_main_fallback(monkeypatch, tmp_path):
    calls = []

    def download(url, *args):
        calls.append(url)
        if url.endswith("listing"):
            raise requests.Timeout()
        return tiny()

    monkeypatch.setattr(photos, "download_thumbnail", download)
    row = {"thumbnail_url": PHOTO + "listing", "primary_image_url": PHOTO + "main"}
    assert photos.resolve_photo(row, CONFIG, cache_dir=tmp_path).content
    assert calls == [row["thumbnail_url"], row["primary_image_url"]]


def test_fallback_only_reads_valid_local_history(monkeypatch, tmp_path):
    old = PHOTO + "old"
    stored(tmp_path, old)
    network(monkeypatch, [requests.Timeout()])
    row = {"primary_image_url": PHOTO, "cached_image_urls": [old]}
    result = photos.resolve_photo(row, CONFIG, cache_dir=tmp_path)
    assert result.content and result.source == "saved"
    assert metrics()["downloads"] == 1 and metrics()["fallback_hits"] == 1


def test_expired_local_fallback_is_rejected(monkeypatch, tmp_path):
    old = PHOTO + "old"
    path = stored(tmp_path, old)
    os.utime(path, (time.time() - 74 * 3600,) * 2)
    network(monkeypatch, [requests.Timeout()])
    assert (
        photos.resolve_photo(
            {"primary_image_url": PHOTO, "cached_image_urls": [old]}, CONFIG, cache_dir=tmp_path
        ).status
        == "failed"
    )


@pytest.mark.parametrize("choice,count", [("Todas", 3), ("Com foto", 2), ("Sem foto", 1)])
def test_photo_filters_do_not_download_or_mutate(choice, count, monkeypatch):
    rows = [{"primary_image_url": PHOTO}, {}, {"detail_image_url": PHOTO}]
    before = json.dumps(rows)
    monkeypatch.setattr(photos, "thumbnail", lambda *a, **k: pytest.fail("filter downloaded"))
    assert len(photos.filter_photos(rows, choice)) == count
    assert json.dumps(rows) == before


def test_metrics_and_recent_failure_window(monkeypatch, tmp_path):
    network(monkeypatch, [requests.Timeout()])
    clock = [time.time()]
    monkeypatch.setattr(photos.time, "time", lambda: clock[0])
    photos.visible_photos(
        [{"primary_image_url": PHOTO, "effective_type": "NAO_ENCONTRADA_NA_BASE"}], CONFIG, cache_dir=tmp_path
    )
    assert metrics()["recent_failures"] == 1
    assert metrics()["batches"][-1]["available"] == 0
    assert metrics()["batches"][-1]["seconds"] >= 0
    clock[0] += 901
    assert metrics()["recent_failures"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cache_ttl_hours": 0},
        {"cache_max_mb": -1},
        {"cache_ttl_hours": float("nan")},
        {"cache_max_mb": float("inf")},
        {"max_concurrent_downloads": 5},
        {"max_redirects": 3},
        {"failure_retry_seconds": 0},
    ],
)
def test_new_config_limits(kwargs):
    with pytest.raises(ValueError):
        VehicleImageConfig(**kwargs)


def test_dashboard_filters_enlargement_and_readonly_data(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from test_matching import motorcycle
    from test_pipeline import result, run
    from test_review_queue import ad, import_base

    from services.scheduler_config import SchedulerConfig

    path = tmp_path / "db.sqlite3"
    import_base(path, [motorcycle()])
    setup = (path, SchedulerConfig(reports=str(tmp_path / "reports"), log_file=str(tmp_path / "pipeline.log")))
    run(setup, result([ad(model="NOVA MOTO", primary_image_url=PHOTO), ad(external_id="2", model="NOVA MOTO")]))
    monkeypatch.setattr(photos, "CACHE_DIR", tmp_path / "images")
    monkeypatch.setattr(photos, "download_thumbnail", lambda *a: tiny())
    monkeypatch.setenv("MOTO_DB", str(path))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
    ui = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    ui.radio(key="navigation").set_value("Fila de revisão").run()
    ui.selectbox(key="photos_queue").set_value("Com foto").run()
    assert len(ui.table[0].value) == 1
    ui.selectbox(key="review_selection").set_value(1).run()
    next(c for c in ui.checkbox if c.label == "Ampliar foto").check().run()
    assert not ui.exception and not ui.error
    ui.selectbox(key="photos_queue").set_value("Sem foto").run()
    assert len(ui.table[0].value) == 1
    ui.radio(key="navigation").set_value("Possíveis novas motos").run()
    assert any(s.label == "Fotos" for s in ui.selectbox)
    assert not ui.exception
    with sqlite3.connect(path) as db:
        assert list(db.iterdump()) == before
