"""Single-process scheduling loop; independent of Streamlit and business rules."""

import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from database.pipeline_repository import PipelineRepository, read_pipeline
from partners.registry import PartnerRegistry
from services.pipeline_lock import ExecutionLock
from services.pipeline_service import run_pipeline
from services.scheduler_config import DEFAULT_CONFIG, load_config, next_due, utcnow


def scheduler_status(database, config, page=0, *, partner_key="wr_motos", registry=None):
    settings = (registry or PartnerRegistry()).get(partner_key)
    config = settings.limits.apply(config)
    data = read_pipeline(database, offset=page * 30, partner=partner_key)
    state = data["scheduler"]
    if not config.enabled or not settings.enabled:
        state_label = "DISABLED"
    elif not state or state["status"] != "RUNNING":
        state_label = "STOPPED"
    elif (utcnow() - datetime.fromisoformat(state["heartbeat_at"])).total_seconds() > config.activity_timeout_seconds:
        state_label = "STALE_ACTIVITY"
    elif state["config_hash"] != config.digest:
        state_label = "CONFIG_PENDING"
    else:
        state_label = "RUNNING"
    data["schedule_status"] = state_label
    due = state["next_run_at"] if state and state_label == "RUNNING" else None
    data["next_local"] = (
        datetime.fromisoformat(due).astimezone(ZoneInfo(config.timezone)).strftime("%d/%m/%Y %H:%M %Z") if due else None
    )
    return data


def serve(
    database,
    config_path=DEFAULT_CONFIG,
    *,
    stop=None,
    clock=utcnow,
    runner=run_pipeline,
    max_ticks=None,
    partner_key="wr_motos",
    registry=None,
):
    registry = registry or PartnerRegistry()
    settings = registry.get(partner_key)

    def configured():
        raw = load_config(config_path)
        return settings.limits.apply(raw) if runner is run_pipeline else raw

    if not Path(database).is_file():
        raise ValueError("Banco não encontrado; importe a base do scanner primeiro")
    stop = stop or threading.Event()
    with ExecutionLock(database, "scheduler", partner=partner_key):
        config = configured()
        if not config.enabled or not settings.enabled:
            with PipelineRepository(database) as repo:
                repo.scheduler(config, None, "DISABLED", partner_key)
            return
        saved = read_pipeline(database, partner=partner_key)["scheduler"]
        due = (
            datetime.fromisoformat(saved["next_run_at"])
            if saved and saved["config_hash"] == config.digest and saved["next_run_at"]
            else next_due(config, clock())
        )
        ticks = 0
        try:
            while not stop.is_set():
                fresh = configured()
                if not fresh.enabled:
                    config = fresh
                    break
                if fresh.digest != config.digest:
                    config, due = fresh, next_due(fresh, clock())
                with PipelineRepository(database) as repo:
                    repo.scheduler(config, due, "RUNNING", partner_key)
                if clock() >= due:
                    # Persist the next slot BEFORE execution; a restart never drains an unbounded backlog.
                    slot = due
                    due = next_due(config, clock())
                    with PipelineRepository(database) as repo:
                        repo.scheduler(config, due, "RUNNING", partner_key)
                    done = threading.Event()

                    def beat():
                        while not done.wait(config.heartbeat_seconds):
                            with PipelineRepository(database) as repo:
                                repo.scheduler(config, due, "RUNNING", partner_key)

                    thread = threading.Thread(target=beat, daemon=True)
                    thread.start()
                    try:
                        runner(
                            database,
                            config,
                            trigger="scheduled",
                            partner_key=partner_key,
                            **({"registry": registry} if runner is run_pipeline else {}),
                            request_key=f"schedule:{config.digest}:{slot.isoformat()}",
                        )
                    finally:
                        done.set()
                        thread.join(timeout=35)
                ticks += 1
                from services.development_alerts import safe_scan

                safe_scan(database)
                from services.prioritization_service import safe_refresh

                safe_refresh(database, partner_key, "scheduled")
                if max_ticks is not None and ticks >= max_ticks:
                    break
                stop.wait(config.heartbeat_seconds)
        finally:
            with PipelineRepository(database) as repo:
                repo.scheduler(
                    config, due if config.enabled else None, "STOPPED" if config.enabled else "DISABLED", partner_key
                )


def launch_manual(database, config_path=DEFAULT_CONFIG, *, request_key, read_only=False, partner_key="wr_motos"):
    PartnerRegistry().get(partner_key, require_enabled=True)
    if read_only:
        raise ValueError("Modo somente leitura: atualização desabilitada")
    path = Path(database).resolve()
    if not path.is_file():
        raise ValueError("Banco não encontrado")
    load_config(config_path)
    args = [
        sys.executable,
        "-m",
        "app.run_pipeline",
        "--partner",
        partner_key,
        "--db",
        str(path),
        "--config",
        str(Path(config_path).resolve()),
        "--request-key",
        request_key,
    ]
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen(
        args,
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **options,
    )
