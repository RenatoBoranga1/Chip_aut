"""Bounded thumbnail storage. Only managed regular files directly inside the cache."""

import hashlib
import logging
import re
import threading
import time
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image

from services.pipeline_lock import ExecutionLock

LOGGER = logging.getLogger(__name__)
DISK_LOCK = threading.RLock()
MANAGED = re.compile(r"[0-9a-f]{64}(?:\.jpg|\.[0-9a-f]{32}\.tmp)\Z")


def digest(url, width):
    # Keep v1 filenames compatible with the already deployed thumbnail cache.
    return hashlib.sha256(f"v1|{width}|{url}".encode()).hexdigest()


def regular_child(path, root):
    return (
        not path.is_symlink() and not path.is_junction() and path.is_file() and path.resolve().parent == root.resolve()
    )


def root_path(directory):
    root = Path(directory).absolute()
    if root.is_symlink() or root.is_junction() or root.resolve() != root:
        raise ValueError("Diretório de fotos não pode ser um redirecionamento")
    return root


def valid_cached(content, width):
    if not content.startswith(b"\xff\xd8\xff"):
        return False
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format != "JPEG" or max(image.size) > width:
                return False
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.load()  # verify alone does not detect every truncated JPEG.
        return True
    except Exception:
        return False


@contextmanager
def guard(directory):
    root = root_path(directory)
    root.mkdir(parents=True, exist_ok=True)
    lock_file = root / "guard.images.lock"
    if lock_file.is_symlink() or lock_file.is_junction():
        raise ValueError("Bloqueio de fotos inválido")
    with DISK_LOCK, ExecutionLock(root / "guard", "images"):
        yield root


def _cleanup(root, config, reserve=0):
    now = time.time()
    maximum = int(config.cache_max_mb * 1024 * 1024)
    files = []
    removed = 0
    for path in root.iterdir():
        if not MANAGED.fullmatch(path.name) or not regular_child(path, root):
            continue
        stat = path.stat()
        expired = now - stat.st_mtime >= (config.cache_ttl_hours * 3600 if path.suffix == ".jpg" else 60)
        if expired:
            path.unlink()
            removed += 1
        else:
            files.append((stat.st_mtime, path.name, path, stat.st_size))
    used = sum(row[3] for row in files)
    for _, _, path, size in sorted(files):
        if used + reserve <= maximum:
            break
        if regular_child(path, root):
            path.unlink()
            used -= size
            removed += 1
    return {"removed": removed, "bytes": used, "limit_bytes": maximum}


def cleanup_cache(directory, config):
    if not config.cache_enabled:
        return {"removed": 0, "bytes": 0}
    try:
        with guard(directory) as root:
            return _cleanup(root, config)
    except Exception as exc:
        LOGGER.warning("Limpeza de fotos indisponível: %s", type(exc).__name__)
        return {"removed": 0, "bytes": None, "error": type(exc).__name__}


def read_cached(url, width, config, directory):
    if not config.cache_enabled:
        return None
    try:
        root = root_path(directory)
        path = root / (digest(url, width) + ".jpg")
        if not regular_child(path, root):
            return None
        stat = path.stat()
        if time.time() - stat.st_mtime >= config.cache_ttl_hours * 3600 or stat.st_size > config.max_image_bytes:
            return None
        content = path.read_bytes()
        if valid_cached(content, width):
            return content
        # Discard only this managed file, and never follow a link.
        with guard(directory) as root:
            if regular_child(path, root):
                path.unlink()
    except Exception as exc:
        LOGGER.debug("Leitura da foto salva indisponível: %s", type(exc).__name__)
    return None


def write_cached(url, width, content, config, directory):
    if not config.cache_enabled or len(content) > int(config.cache_max_mb * 1024 * 1024):
        return False
    temporary = None
    try:
        with guard(directory) as root:
            target = root / (digest(url, width) + ".jpg")
            if target.is_symlink() or target.is_junction():
                return False
            _cleanup(root, config, reserve=len(content))
            temporary = root / (digest(url, width) + f".{uuid4().hex}.tmp")
            with temporary.open("xb") as stream:
                stream.write(content)
            temporary.replace(target)
            _cleanup(root, config)
            return True
    except Exception as exc:
        LOGGER.warning("Não foi possível salvar miniatura; usando memória: %s", type(exc).__name__)
        if temporary is not None:
            try:
                if regular_child(temporary, temporary.parent):
                    temporary.unlink()
            except OSError:
                pass
        return False
