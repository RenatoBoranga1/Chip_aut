"""One pipeline for CLI, background scheduler and dashboard requests."""

import hashlib
import json
import logging
import re
import threading
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from logging.handlers import RotatingFileHandler
from pathlib import Path

from database.partner_repository import PartnerRepository
from database.pipeline_repository import PipelineRepository, read_pipeline
from database.repository import encode
from database.transaction import atomic_database
from database.vehicle_images import save_vehicle_images
from matching.review_policy import load_policy
from matching.rules import load_matching_rules
from partners.images import IMAGE_FIELDS
from partners.wr_http import WRHTTPSource
from partners.wr_motos import WRMotosCollector
from services.alert_service import enqueue, safe_process
from services.collection_service import fetch_collection
from services.coverage_service import build_coverage
from services.pipeline_lock import AlreadyRunning, ExecutionLock

LOGGER = logging.getLogger(__name__)


def setup_log(config):
    target = Path(config.log_file).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not any(getattr(h, "baseFilename", None) == str(target) for h in LOGGER.handlers):
        handler = RotatingFileHandler(target, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)


@contextmanager
def activity(database, run_id, interval):
    stopped = threading.Event()

    def beat():
        while not stopped.wait(interval):
            try:
                with PipelineRepository(database) as repo:
                    repo.beat(run_id)
            except Exception:
                LOGGER.exception("Sinal de atividade não pôde ser registrado")

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=35)


def transient(errors):
    return bool(errors) and all(
        e.get("code") in {"Timeout", "ReadTimeout", "ConnectTimeout", "ConnectionError"}
        or (e.get("code") == "RuntimeError" and re.fullmatch(r"HTTP 5[0-9]{2}", e.get("detail", "")))
        for e in errors
    )


def default_collector(config, folder):
    return WRMotosCollector(
        source=WRHTTPSource(
            delay=config.delay_seconds,
            timeout_ms=int(config.request_timeout_seconds * 1000),
            max_pages=config.max_pages,
            evidence_dir=folder,
        ),
        cache_ttl=0,
    )


def fingerprint(result, repo):
    # Exclude observation time and transport evidence, not identity, price, mileage or original text.
    ads = [
        {k: v for k, v in asdict(a).items() if k not in {"collected_at", "raw_data", *IMAGE_FIELDS}}
        for a in result.advertisements
    ]
    base = repo.connection.execute("SELECT MAX(id) FROM imports").fetchone()[0]
    if base is None:
        raise ValueError("Importe a base do scanner antes da atualização")
    versions = [
        repo.connection.execute(f"SELECT COALESCE(MAX(id),0) FROM {t}").fetchone()[0]
        for t in ("review_decisions", "matching_reviews", "matching_memory")
    ]
    payload = [
        sorted(ads, key=lambda a: a["external_id"]),
        base,
        versions,
        load_matching_rules().to_dict(),
        load_policy(),
        "pipeline-5.0",
    ]
    return hashlib.sha256(encode(payload).encode()).hexdigest()


def run_pipeline(database, config, *, trigger="manual", request_key=None, collector_factory=None, sleeper=time.sleep):
    if trigger not in {"manual", "scheduled"}:
        raise ValueError("Origem da execução inválida")
    database = Path(database).resolve()
    if not database.is_file():
        raise ValueError("Banco não encontrado; importe a base do scanner primeiro")
    setup_log(config)
    # Migrations before the lock allow a skipped attempt to be recorded as well.
    with PipelineRepository(database):
        pass
    lock = ExecutionLock(database)
    try:
        lock.__enter__()
    except AlreadyRunning:
        with atomic_database(database):
            with PipelineRepository(database) as repo:
                previous = repo.existing(request_key)
                if previous:
                    return read_pipeline(database, run_id=previous)["runs"][0]
                skipped = repo.start(trigger, config.digest, request_key, "SKIPPED_ALREADY_RUNNING")
                repo.finish(skipped, "SKIPPED_ALREADY_RUNNING", 0, {}, "Atualização já em andamento")
        return read_pipeline(database, run_id=skipped)["runs"][0]
    started = time.monotonic()
    run_id = None
    summary = {"attempts": 0, "warnings": {}, "errors": []}
    alert_context = {"stage": "preflight"}
    try:
        safe_process(database)
        with PipelineRepository(database) as repo:
            repo.recover()
            previous = repo.existing(request_key)
            if previous:
                return read_pipeline(database, run_id=previous)["runs"][0]
            run_id = repo.start(trigger, config.digest, request_key)
            summary["ads_before"] = repo.connection.execute(
                "SELECT COUNT(*) FROM partner_advertisements WHERE partner='wr_motos' AND not_seen_in_latest_collection=0"
            ).fetchone()[0]
            if repo.connection.execute("SELECT MAX(id) FROM imports").fetchone()[0] is None:
                raise ValueError("Importe a base do scanner antes da atualização")
        LOGGER.info("Execução %s iniciada; origem=%s", run_id, trigger)
        folder = Path(config.reports) / f"run-{run_id:06d}"
        factory = collector_factory or default_collector
        with activity(database, run_id, config.heartbeat_seconds):
            alert_context["stage"] = "collection"
            for attempt in range(config.max_retries + 1):
                summary["attempts"] = attempt + 1
                LOGGER.info("Execução %s: coleta; tentativa=%s", run_id, attempt + 1)
                result = fetch_collection("wr_motos", factory(config, folder / f"attempt-{attempt + 1}"))
                if result.partner != "wr_motos":
                    raise ValueError("Parceiro retornado pela coleta é inválido")
                if result.complete and not result.errors:
                    break
                alert_context["partial"] = bool(result.advertisements) and not result.complete
                summary["errors"].extend(result.errors)
                if not transient(result.errors) or attempt == config.max_retries:
                    raise ValueError("Coleta incompleta ou bloqueada; estoque e cobertura anteriores preservados")
                delay = min(300, config.retry_backoff_seconds * (2**attempt))
                LOGGER.warning("Execução %s: falha transitória; nova tentativa em %ss", run_id, delay)
                sleeper(delay)
            summary["warnings"] = dict(Counter(w for a in result.advertisements for w in a.parse_warnings))
            alert_context.update(stage="publication", partial=False)
            # Existing services join this transaction. Any later failure rolls back collection, matching AND queue.
            LOGGER.info("Execução %s: persistência, correspondência, memória, fila e cobertura", run_id)
            with atomic_database(database):
                with PipelineRepository(database) as repo:
                    alert_context["review_max_before"] = repo.connection.execute(
                        "SELECT COALESCE(MAX(id),0) FROM review_items"
                    ).fetchone()[0]
                    previous_coverage = repo.connection.execute(
                        "SELECT import_id FROM coverage_runs ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    alert_context["previous_base"] = previous_coverage[0] if previous_coverage else None
                    before = {
                        r[0]
                        for r in repo.connection.execute(
                            "SELECT external_id FROM partner_advertisements WHERE partner='wr_motos' AND not_seen_in_latest_collection=0"
                        )
                    }
                    known = {
                        r[0]
                        for r in repo.connection.execute(
                            "SELECT external_id FROM partner_advertisements WHERE partner='wr_motos'"
                        )
                    }
                    stamp = fingerprint(result, repo)
                    prior = repo.connection.execute(
                        "SELECT collection_run_id,summary_json FROM pipeline_runs WHERE status IN ('SUCCESS','PARTIAL_SUCCESS') AND fingerprint=? ORDER BY id DESC LIMIT 1",
                        (stamp,),
                    ).fetchone()
                    latest = repo.connection.execute(
                        "SELECT MAX(id) FROM partner_collections WHERE partner='wr_motos'"
                    ).fetchone()[0]
                    reuse = prior is not None and prior[0] == latest
                    current = {a.external_id for a in result.advertisements}
                    alert_context["new_ids"] = sorted(current - known)
                    alert_context["observation"] = sorted(
                        (a.external_id, a.collected_at) for a in result.advertisements
                    )
                    summary.update(
                        ads_before=len(before),
                        ads_after=len(current),
                        new=len(current - known),
                        reappeared=len(current & before),
                        returned=len((current & known) - before),
                        disappeared=len(before - current),
                        unchanged=len(current & before),
                        reused=reuse,
                        collected_at=result.collected_at,
                    )
                if reuse:
                    with PipelineRepository(database) as repo:
                        repo.refresh_observations(result)
                        save_vehicle_images(repo.connection, result)
                    collection_id = prior[0]
                    old = json.loads(prior[1])
                    summary.update({k: old[k] for k in ("matching_counts", "queue_counts", "coverage_counts")})
                else:
                    with PartnerRepository(database) as repo:
                        collection_id = repo.save_collection(result)
                    report = build_coverage(collection_id, database, folder)
                    summary.update(
                        matching_counts=dict(
                            Counter(
                                i["automatic_result"]["match_type"]
                                for group in report["groups"].values()
                                for i in group
                            )
                        ),
                        queue_counts=report["review_queue"],
                        coverage_counts=report["counts"],
                    )
                status = "PARTIAL_SUCCESS" if summary["warnings"] or summary["errors"] else "SUCCESS"
                with PipelineRepository(database) as repo:
                    repo.finish(
                        run_id,
                        status,
                        round(time.monotonic() - started, 3),
                        summary,
                        collection_id=collection_id,
                        fingerprint=stamp,
                    )
                    alert_context["coverage_id"] = repo.connection.execute(
                        "SELECT MAX(id) FROM coverage_runs WHERE collection_id=?", (collection_id,)
                    ).fetchone()[0]
                    alert_context["review_event_max"] = repo.connection.execute(
                        "SELECT COALESCE(MAX(id),0) FROM review_events"
                    ).fetchone()[0]
                    enqueue(repo, run_id, alert_context)
        safe_process(database)
        LOGGER.info(
            "Execução %s concluída; resultado=%s; anúncios=%s; avisos=%s",
            run_id,
            status,
            summary["ads_after"],
            summary["warnings"],
        )
    except BaseException as exc:
        LOGGER.exception("Execução %s falhou; duração=%.3fs", run_id, time.monotonic() - started)
        if run_id is not None:
            summary.update(ads_after=summary.get("ads_before", 0), disappeared=None, new=0, reappeared=0)
            for field in ("matching_counts", "queue_counts", "coverage_counts"):
                summary.pop(field, None)
            with atomic_database(database), PipelineRepository(database) as repo:
                repo.finish(
                    run_id,
                    "CANCELLED" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "FAILED",
                    round(time.monotonic() - started, 3),
                    summary,
                    str(exc),
                )
                if not isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    next_run = repo.connection.execute(
                        "SELECT next_run_at FROM scheduler_state WHERE id=1 AND status='RUNNING'"
                    ).fetchone()
                    alert_context["next_run_at"] = next_run[0] if next_run else None
                    enqueue(repo, run_id, alert_context)
            safe_process(database)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)) or run_id is None:
            raise
    finally:
        lock.__exit__()
    return read_pipeline(database, run_id=run_id)["runs"][0]
