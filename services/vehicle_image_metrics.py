"""Local process metrics only; no external telemetry or vehicle classification."""

import json
import logging
import threading
import time
from collections import Counter, deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOCK = threading.Lock()
COUNTS = Counter()
FAILURES = deque(maxlen=1000)
BATCHES = deque(maxlen=50)
LOGGER = logging.getLogger(__name__)


def count(name, amount=1):
    with LOCK:
        COUNTS[name] += amount
        if name == "failures":
            FAILURES.append(time.time())


def metrics():
    with LOCK:
        return {**COUNTS, "recent_failures": sum(t >= time.time() - 900 for t in FAILURES), "batches": list(BATCHES)}


def record_batch(seconds, visible, available):
    result = {"seconds": round(seconds, 4), "visible": visible, "available": available}
    with LOCK:
        BATCHES.append(result)
    try:
        if not LOGGER.handlers:
            destination = Path(__file__).resolve().parents[1] / "logs/vehicle_images.log"
            destination.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(destination, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
            LOGGER.addHandler(handler)
            LOGGER.setLevel(logging.INFO)
        LOGGER.info(json.dumps({**result, "counts": {k: v for k, v in metrics().items() if k != "batches"}}))
    except OSError:
        pass  # Diagnostics cannot block the UI.
    return result


def reset_metrics():
    with LOCK:
        COUNTS.clear()
        FAILURES.clear()
        BATCHES.clear()
