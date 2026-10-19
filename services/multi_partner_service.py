"""Independent partner executions reuse the existing pipeline and partner locks."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from database.pipeline_repository import PipelineRepository
from partners.registry import PartnerRegistry
from services.pipeline_service import run_pipeline


def run_all(database, config, *, registry=None, request_key=None, runner=None):
    default_registry = registry is None
    registry = registry or PartnerRegistry()
    runner = runner or run_pipeline
    entries = registry.list(enabled_only=True)
    from services.partner_operations_config import INBOX_ENV, inbox_root

    inbox_configured = default_registry and any(inbox_root(key) is not None for key in INBOX_ENV)
    operational = []
    if default_registry:
        from partners.integration import operational_modes

        operational = [
            entry
            for entry in operational_modes()
            if entry["partner_key"] != "wr_motos" and entry["automation_enabled"] and entry["supports_scheduler"]
        ]
    if not entries and not operational and not inbox_configured:
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
    with ThreadPoolExecutor(max_workers=max(1, len(entries)), thread_name_prefix="partner") as pool:
        pending = {pool.submit(execute, p): p.partner_key for p in entries}
        for future in as_completed(pending):
            results[pending[future]] = future.result()
    result = {p.partner_key: results[p.partner_key] for p in entries}
    if operational:
        from services.partner_operation_scheduler import run_operation

        for entry in operational:
            key = entry["partner_key"]
            if key not in result:
                result[key] = run_operation(database, config, partner_key=key)
    if inbox_configured:
        from services.partner_inbox_service import poll_inboxes

        output = poll_inboxes(database)
        result["partner_inbox"] = {
            "status": "FAILED" if output.get("status") == "FAILED" else "SUCCESS",
            "summary": output,
        }
    return result
