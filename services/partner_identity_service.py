"""Read-only cross-partner occurrences. Never propagates human decisions."""

from collections import defaultdict
from dataclasses import replace

from database.repository import encode
from matching.review_policy import complete_identity, identity
from partners.registry import PartnerRegistry
from services.dashboard_service import DashboardService

SAFE = {
    "EXATO_NORMALIZADO",
    "EXATO_CONFIRMADO_HUMANAMENTE",
    "CONFIRMADO_MANUALMENTE",
    "CONFIRMADO_AUSENTE_NA_BASE",
    "NAO_ENCONTRADA_NA_BASE",
}


def grouping_key(row):
    ident = identity(row)
    ident.pop("partner")
    reliable = (
        complete_identity(ident)
        and row.get("effective_type") in SAFE
        and row.get("human_status") != "Em dúvida"
        and not (set(row.get("parse_warnings", [])) - {"FILTROS_ZERO_KM_CONFLITANTES"})
    )
    if not reliable:
        ident["origin_scope"] = [row["partner"], row["external_id"]]
    return encode(ident)


def group_occurrences(rows):
    groups = defaultdict(dict)
    for row in rows:
        groups[grouping_key(row)][(row["partner"], row["external_id"])] = row
    return [
        {
            "identity": key,
            "manufacturer": next(iter(origins.values())).get("manufacturer"),
            "model": next(iter(origins.values())).get("model"),
            "year": next(iter(origins.values())).get("year"),
            "partner_count": len({p for p, _ in origins}),
            "occurrence_count": len(origins),
            "origins": list(origins.values()),
        }
        for key, origins in groups.items()
    ]


def cross_partner_opportunities(config, registry=None):
    registry = registry or PartnerRegistry()
    rows = []
    for entry in registry.list():
        groups = DashboardService(replace(config, partner=entry.partner_key)).opportunities()
        rows.extend({**row, "opportunity_status": status} for status, group in groups.items() for row in group)
    return group_occurrences(rows)


def stock_origins(config, row, registry=None):
    registry = registry or PartnerRegistry()
    key = grouping_key(row)
    return [
        candidate
        for entry in registry.list()
        for candidate in DashboardService(replace(config, partner=entry.partner_key)).snapshot()["stock"]
        if grouping_key(candidate) == key
    ]
