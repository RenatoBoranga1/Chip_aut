"""Single-process scheduling loop; independent of Streamlit and business rules."""

import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from database.pipeline_repository import PipelineRepository, read_pipeline
from services.pipeline_lock import ExecutionLock
from services.pipeline_service import run_pipeline
from services.scheduler_config import DEFAULT_CONFIG, load_config, next_due, utcnow


def scheduler_status(database, config, page=0):
    data = read_pipeline(database, offset=page * 30)
    state = data["scheduler"]
    if not config.enabled:
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


def serve(database, config_path=DEFAULT_CONFIG, *, stop=None, clock=utcnow, runner=run_pipeline, max_ticks=None):
    if not Path(database).is_file():
        raise ValueError("Banco não encontrado; importe a base do scanner primeiro")
    stop = stop or threading.Event()
    with ExecutionLock(database, "scheduler"):
        config = load_config(config_path)
        if not config.enabled:
            with PipelineRepository(database) as repo:
                repo.scheduler(config, None, "DISABLED")
            return
        saved = read_pipeline(database)["scheduler"]
        due = (
            datetime.fromisoformat(saved["next_run_at"])
            if saved and saved["config_hash"] == config.digest and saved["next_run_at"]
            else next_due(config, clock())
        )
        ticks = 0
        try:
            while not stop.is_set():
                fresh = load_config(config_path)
                if not fresh.enabled:
                    config = fresh
                    break
                if fresh.digest != config.digest:
                    config, due = fresh, next_due(fresh, clock())
                with PipelineRepository(database) as repo:
                    repo.scheduler(config, due, "RUNNING")
                if clock() >= due:
                    # Persist the next slot BEFORE execution; a restart never drains an unbounded backlog.
                    slot = due
                    due = next_due(config, clock())
                    with PipelineRepository(database) as repo:
                        repo.scheduler(config, due, "RUNNING")
                    done = threading.Event()

                    def beat():
                        while not done.wait(config.heartbeat_seconds):
                            with PipelineRepository(database) as repo:
                                repo.scheduler(config, due, "RUNNING")

                    thread = threading.Thread(target=beat, daemon=True)
                    thread.start()
                    try:
                        runner(
                            database,
                            config,
                            trigger="scheduled",
                            request_key=f"schedule:{config.digest}:{slot.isoformat()}",
                        )
                    finally:
                        done.set()
                        thread.join(timeout=35)
                ticks += 1
                if max_ticks is not None and ticks >= max_ticks:
                    break
                stop.wait(config.heartbeat_seconds)
        finally:
            with PipelineRepository(database) as repo:
                repo.scheduler(config, due if config.enabled else None, "STOPPED" if config.enabled else "DISABLED")


def launch_manual(database, config_path=DEFAULT_CONFIG, *, request_key, read_only=False):
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
