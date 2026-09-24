"""On-demand, bounded raster thumbnails. Never downloads a whole inventory."""

import hashlib
import ipaddress
import logging
import socket
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import requests
from PIL import Image, ImageOps

from partners.images import image_url

LOGGER = logging.getLogger(__name__)
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "images"
ALLOWED_HOSTS = frozenset({"www.wrmotos.com.br", "media.integradordeanuncios.com.br"})
LOCKS = [threading.Lock() for _ in range(32)]
POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="vehicle-photo")


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
        for hop in range(3):
            safe_download_url(url)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Prazo da foto excedido")
            with session.get(url, timeout=remaining, allow_redirects=False, stream=True) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if hop == 2 or not response.headers.get("Location"):
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
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(BytesIO(body)) as original:
                        if (
                            original.format not in {"JPEG", "PNG", "WEBP"}
                            or original.width * original.height > 20_000_000
                        ):
                            raise ValueError("Formato ou dimensões inválidos")
                        original.thumbnail((width, width), Image.Resampling.LANCZOS)
                        thumb = ImageOps.exif_transpose(original).convert("RGB")
                        output = BytesIO()
                        thumb.save(output, "JPEG", quality=82)
                        return output.getvalue()
    raise ValueError("Foto indisponível")


@lru_cache(maxsize=256)
def _thumbnail(url, width, config, cache_dir, time_bucket):
    digest = hashlib.sha256(f"v1|{width}|{url}".encode()).hexdigest()
    target = Path(cache_dir) / (digest + ".jpg")
    with LOCKS[int(digest[:2], 16) % len(LOCKS)]:
        try:
            if config.cache_enabled and target.is_file() and time.time() - target.stat().st_mtime < 86400:
                content = target.read_bytes()
                with Image.open(BytesIO(content)) as cached:
                    if cached.format == "JPEG" and max(cached.size) <= width:
                        cached.verify()
                        return content
            content = download_thumbnail(url, width, config)
            if config.cache_enabled:
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_suffix(f".{uuid4().hex}.tmp")
                    temporary.write_bytes(content)
                    temporary.replace(target)
                except OSError:
                    LOGGER.warning("Não foi possível gravar miniatura; usando memória")
            return content
        except Exception as exc:
            LOGGER.debug("Foto indisponível: %s", type(exc).__name__)
            return None  # Includes expired URLs, TLS, decode, timeouts and filesystem failures.


def thumbnail(url, config, *, detail=False, cache_dir=None):
    if not config.enabled or not url:
        return None
    width = 420 if detail else config.thumbnail_width
    # Negative results live five minutes too; UI reruns cannot hammer a broken URL.
    return _thumbnail(url, width, config, str(cache_dir or CACHE_DIR), int(time.time() // 300))


def visible_thumbnails(rows, config):
    from services.vehicle_image_config import should_show_vehicle_image

    urls = list(
        dict.fromkeys(
            r.get("primary_image_url")
            for r in rows[:8]
            if should_show_vehicle_image(r, config) and r.get("primary_image_url")
        )
    )
    return dict(zip(urls, POOL.map(lambda url: thumbnail(url, config), urls)))
