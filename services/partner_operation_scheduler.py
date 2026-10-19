"""Optional schedules route to an authorized source or staging, never file import."""

from types import SimpleNamespace

from partners.config import PartnerLimits
from partners.integration import PartnerIntegrationMode, integration


class OperationScheduleRegistry:
    def get(self, key):
        entry = integration(key)
        from services.partner_operations_config import INBOX_ENV, inbox_root

        inbox = key in INBOX_ENV and inbox_root(key) is not None
        return SimpleNamespace(
            enabled=inbox or entry.enabled and entry.automation_enabled and entry.supports_scheduler,
            limits=PartnerLimits(retries=0),
        )


def run_operation(database, config, *, partner_key, **_kwargs):
    entry = integration(partner_key)
    from services.partner_operations_config import INBOX_ENV, inbox_root

    inbox = partner_key in INBOX_ENV and inbox_root(partner_key) is not None
    if not entry.automation_enabled or not entry.supports_scheduler:
        if inbox:
            from services.partner_inbox_service import PartnerInboxService

            return {
                "partner": partner_key,
                "status": "SUCCESS",
                "inbox": PartnerInboxService(database).scan(partner_key, force=False),
            }
        return {"partner": partner_key, "status": "DISABLED"}
    try:
        if entry.integration_mode == PartnerIntegrationMode.STAGED_COLLECTION:
            from services.motonil_staging_service import MotonilStagingService

            output = MotonilStagingService(database, reports=config.reports).collect()
        elif entry.integration_mode == PartnerIntegrationMode.AUTHENTICATED_COLLECTION:
            from partners.authenticated_source import collect_authenticated

            output = collect_authenticated(
                database, confirmed=True, reviewer="agendamento autorizado", reports=config.reports
            )
        else:
            return {"partner": partner_key, "status": "DISABLED"}
        return {"partner": partner_key, "status": "SUCCESS", "summary": output}
    except Exception:
        return {
            "partner": partner_key,
            "status": "FAILED",
            "error_summary": "Atualização não concluída; consulte as pendências operacionais.",
        }


def serve_operation(database, config_path, *, partner_key, **kwargs):
    from services.scheduler_service import serve

    return serve(
        database,
        config_path,
        partner_key=partner_key,
        registry=OperationScheduleRegistry(),
        runner=run_operation,
        **kwargs,
    )
