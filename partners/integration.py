"""Operational capabilities are independent of the public collector allowlist."""

import os
from dataclasses import asdict, dataclass, replace
from enum import StrEnum


class PartnerIntegrationMode(StrEnum):
    PUBLIC_COLLECTION = "PUBLIC_COLLECTION"
    AUTHENTICATED_COLLECTION = "AUTHENTICATED_COLLECTION"
    FILE_IMPORT = "FILE_IMPORT"
    STAGED_COLLECTION = "STAGED_COLLECTION"


@dataclass(frozen=True)
class PartnerIntegration:
    partner_key: str
    display_name: str
    integration_mode: PartnerIntegrationMode
    source: str
    enabled: bool = True
    automation_enabled: bool = False
    requires_authentication: bool = False
    requires_human_triage: bool = False
    supports_scheduler: bool = False
    supports_manual_import: bool = False
    is_public: bool = False
    is_authorized: bool = False
    supports_incremental: bool = True
    last_validated_at: str = "2026-10-09"


INTEGRATIONS = {
    "wr_motos": PartnerIntegration(
        "wr_motos",
        "WR Motos",
        PartnerIntegrationMode.PUBLIC_COLLECTION,
        "wr_motos",
        automation_enabled=True,
        supports_scheduler=True,
        is_public=True,
        is_authorized=True,
    ),
    "thomas_motos": PartnerIntegration(
        "thomas_motos",
        "Thomas Motos",
        PartnerIntegrationMode.FILE_IMPORT,
        "Arquivo autorizado / AutoCerto com credencial",
        supports_manual_import=True,
    ),
    "motonil": PartnerIntegration(
        "motonil",
        "Motonil",
        PartnerIntegrationMode.STAGED_COLLECTION,
        "https://www.motonil.com.br/MOTOS",
        requires_human_triage=True,
        is_public=True,
        is_authorized=True,
    ),
    "moto_marques": PartnerIntegration(
        "moto_marques",
        "Moto Marques Multimarcas",
        PartnerIntegrationMode.FILE_IMPORT,
        "Arquivo autorizado da unidade Multimarcas",
        supports_manual_import=True,
    ),
}


def integration(key):
    try:
        entry = INTEGRATIONS[key]
        if (
            key == "thomas_motos"
            and os.environ.get("THOMAS_API_TOKEN")
            and os.environ.get("THOMAS_AUTHORIZED") == "true"
            and os.environ.get("THOMAS_MOTORCYCLE_TYPE")
        ):
            return replace(
                entry,
                integration_mode=PartnerIntegrationMode.AUTHENTICATED_COLLECTION,
                requires_authentication=True,
                is_authorized=True,
                supports_scheduler=True,
                automation_enabled=os.environ.get("THOMAS_AUTOMATION_ENABLED") == "true"
                and os.environ.get("THOMAS_AUTH_VALIDATED") == "true",
            )
        if key == "motonil":
            return replace(
                entry,
                supports_scheduler=True,
                automation_enabled=os.environ.get("MOTONIL_AUTOMATION_ENABLED") == "true",
            )
        return entry
    except KeyError:
        raise ValueError("Parceiro operacional desconhecido") from None


def operational_modes():
    return [asdict(integration(key)) for key in INTEGRATIONS]


def operational_entries(registry, database):
    from types import SimpleNamespace

    from database.inventory_repository import read_operations

    entries = registry.list()
    keys = {p.partner_key for p in entries}
    return entries + [
        SimpleNamespace(partner_key=p["partner_key"], display_name=p["display_name"], enabled=True)
        for p in read_operations(database)["partners"]
        if p["active_ads"] and p["partner_key"] not in keys
    ]
