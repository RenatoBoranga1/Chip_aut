"""Independent partner executions reuse the existing pipeline and partner locks."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from database.pipeline_repository import PipelineRepository
from partners.registry import PartnerRegistry
from services.pipeline_service import run_pipeline


def run_all(database, config, *, registry=None, request_key=None, runner=None):
    registry = registry or PartnerRegistry()
    runner = runner or run_pipeline
    entries = registry.list(enabled_only=True)
    if not entries:
        return {}
    if not Path(database).is_file():
        raise ValueError("Banco não encontrado; importe a base do scanner primeiro")
    # Bootstrap migrations once before concurrent workers; no global execution lock.
    with PipelineRepository(database):
        pass

    def execute(entry):
        try:
            return runner(
                database,
                entry.limits.apply(config),
                partner_key=entry.partner_key,
                registry=registry,
                request_key=request_key,
            )
        except Exception as exc:
            return {"partner": entry.partner_key, "status": "FAILED", "error_summary": str(exc)}

    results = {}
    with ThreadPoolExecutor(max_workers=len(entries), thread_name_prefix="partner") as pool:
        pending = {pool.submit(execute, p): p.partner_key for p in entries}
        for future in as_completed(pending):
            results[pending[future]] = future.result()
    return {p.partner_key: results[p.partner_key] for p in entries}
