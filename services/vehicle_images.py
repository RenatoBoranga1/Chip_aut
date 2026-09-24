"""On-demand, bounded raster thumbnails. Never downloads a whole inventory."""

import ipaddress
import logging
import socket
import threading
import time
import warnings
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from PIL import Image, ImageOps

from partners.images import image_url
from services.vehicle_image_cache import cleanup_cache, digest, read_cached, write_cached
from services.vehicle_image_metrics import count, record_batch

LOGGER = logging.getLogger(__name__)
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "images"
ALLOWED_HOSTS = frozenset({"www.wrmotos.com.br", "media.integradordeanuncios.com.br"})
LOCKS = [threading.Lock() for _ in range(32)]
POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="vehicle-photo")
NETWORK_LIMIT = threading.BoundedSemaphore(4)
MEMORY_LOCK = threading.Lock()
MEMORY = OrderedDict()


@lru_cache(maxsize=4)
def configured_limit(size):
    return threading.BoundedSemaphore(size)


def raster_format(content):
    if content.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "WEBP"
    raise ValueError("Conteúdo não tem assinatura de foto permitida")


def safe_download_url(url):
    if image_url(url, "") != url:
        raise ValueError("URL de foto inválida")
    host = urlsplit(url).hostname
    if host not in ALLOWED_HOSTS:
        raise ValueError("Origem de foto não observada no parceiro")
    addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Destino de foto não público")


def download_thumbnail(url, width, config):
    deadline = time.monotonic() + config.request_timeout_seconds
    with requests.Session() as session:
        session.headers.update({"User-Agent": "MotoCoverageMonitor/0.3"})
        for hop in range(config.max_redirects + 1):
            safe_download_url(url)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Prazo da foto excedido")
            with session.get(url, timeout=remaining, allow_redirects=False, stream=True) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if hop == config.max_redirects or not response.headers.get("Location"):
                        raise ValueError("Redirecionamentos de foto excedidos")
                    url = urljoin(url, response.headers["Location"])
                    continue
                if response.status_code != 200:
                    raise ValueError("Foto indisponível")
                kind = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if kind not in {"image/jpeg", "image/png", "image/webp"}:
                    raise ValueError("Conteúdo não é uma foto permitida")
                if int(response.headers.get("Content-Length", "0")) > config.max_image_bytes:
                    raise ValueError("Foto excede limite")
                body = bytearray()
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > config.max_image_bytes or time.monotonic() > deadline:
                        raise ValueError("Limite da foto excedido")
                signature = raster_format(body)
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(BytesIO(body)) as original:
                        if original.format != signature or original.width * original.height > 20_000_000:
                            raise ValueError("Formato ou dimensões inválidos")
                        original.thumbnail((width, width), Image.Resampling.LANCZOS)
                        thumb = ImageOps.exif_transpose(original).convert("RGB")
                        output = BytesIO()
                        thumb.save(output, "JPEG", quality=82)
                        return output.getvalue()
    raise ValueError("Foto indisponível")


def _thumbnail(url, width, config, cache_dir, time_bucket):
    key = (url, width, config, str(cache_dir))
    with LOCKS[int(digest(url, width)[:2], 16) % len(LOCKS)]:
        now = time.time()
        with MEMORY_LOCK:
            saved = MEMORY.get(key)
            if saved and saved[0] > now:
                MEMORY.move_to_end(key)
                count("memory_hits" if saved[1] else "failure_cache_hits")
                return saved[1]
            MEMORY.pop(key, None)
        content = read_cached(url, width, config, cache_dir)
        if content:
            count("disk_hits")
            # Do not extend the disk expiration through an in-memory entry.
            return content
        count("cache_misses")
        try:
            with NETWORK_LIMIT, configured_limit(config.max_concurrent_downloads):
                count("downloads")
                content = download_thumbnail(url, width, config)
            write_cached(url, width, content, config, cache_dir)
        except Exception as exc:
            LOGGER.debug("Foto indisponível: %s", type(exc).__name__)
            count("failures")
            content = None
        ttl = min(300, config.cache_ttl_hours * 3600) if content else config.failure_retry_seconds
        with MEMORY_LOCK:
            MEMORY[key] = (time.time() + ttl, content)
            MEMORY.move_to_end(key)
            while len(MEMORY) > 256:
                MEMORY.popitem(last=False)
        return content


def clear_memory():
    with MEMORY_LOCK:
        MEMORY.clear()


# Compatibility with existing callers/tests that clear the earlier LRU cache.
_thumbnail.cache_clear = clear_memory


def thumbnail(url, config, *, detail=False, cache_dir=None):
    if not config.enabled or not url:
        return None
    width = 420 if detail else config.thumbnail_width
    return _thumbnail(url, width, config, str(cache_dir or CACHE_DIR), None)


@dataclass(frozen=True)
class PhotoResult:
    content: bytes | None = None
    status: str = "missing"
    source: str | None = None


def photo_urls(row):
    # These are already-known URLs; rendering never opens an individual advertisement.
    return list(
        dict.fromkeys(
            u
            for u in (
                row.get("thumbnail_url"),
                row.get("listing_image_url"),
                row.get("primary_image_url"),
                row.get("detail_image_url"),
            )
            if u
        )
    )[:2]


def resolve_photo(row, config, *, detail=False, cache_dir=None, loader=None):
    if not config.enabled:
        return PhotoResult(status="disabled")
    loader = loader or thumbnail
    urls = photo_urls(row)
    for url in urls:
        options = {}
        if detail:
            options["detail"] = True
        if cache_dir is not None:
            options["cache_dir"] = cache_dir
        content = loader(url, config, **options)
        if content:
            return PhotoResult(content, "available", "current")
    previous = list(dict.fromkeys([*urls, *row.get("cached_image_urls", [])]))[:5]
    for url in previous:
        for width in [420, config.thumbnail_width] if detail else [config.thumbnail_width, 420]:
            content = read_cached(url, width, config, cache_dir or CACHE_DIR)
            if content:
                count("fallback_hits")
                return PhotoResult(content, "available", "saved")
    return PhotoResult(status="failed" if urls else "missing")


def visible_photos(rows, config, *, cache_dir=None):
    from services.vehicle_image_config import should_show_vehicle_image

    start = time.perf_counter()
    visible = rows[:8]
    if config.enabled:
        cleanup_cache(cache_dir or CACHE_DIR, config)
    keys = [tuple([*photo_urls(r), "|", *r.get("cached_image_urls", [])]) for r in visible]
    unique = {key: r for key, r in zip(keys, visible) if should_show_vehicle_image(r, config)}
    photos = dict(zip(unique, POOL.map(lambda r: resolve_photo(r, config, cache_dir=cache_dir), unique.values())))
    output = [
        photos.get(k, PhotoResult(status="disabled"))
        if should_show_vehicle_image(r, config)
        else PhotoResult(status="disabled")
        for k, r in zip(keys, visible)
    ]
    record_batch(
        time.perf_counter() - start, sum(p.status != "disabled" for p in output), sum(bool(p.content) for p in output)
    )
    return output


def visible_thumbnails(rows, config):
    return {
        r["primary_image_url"]: p.content
        for r, p in zip(rows[:8], visible_photos(rows, config))
        if r.get("primary_image_url") and p.status != "disabled"
    }


def filter_photos(rows, choice="Todas"):
    if choice not in {"Todas", "Com foto", "Sem foto"}:
        raise ValueError("Filtro de fotos inválido")
    return [r for r in rows if choice == "Todas" or bool(photo_urls(r)) == (choice == "Com foto")]


def photo_summary(rows, config):
    from services.vehicle_image_config import should_show_vehicle_image

    relevant = [r for r in rows if should_show_vehicle_image(r, config)]
    with_photo = sum(bool(photo_urls(r)) for r in relevant)
    return {"relevant": len(relevant), "with_photo": with_photo, "without_photo": len(relevant) - with_photo}
