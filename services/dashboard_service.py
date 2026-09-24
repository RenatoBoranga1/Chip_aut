"""Presentation-ready operational reads and commands; no Streamlit dependency."""

import logging
import os
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from database.dashboard_repository import DashboardRepository
from database.review_repository import ReviewRepository
from database.vehicle_images import latest_vehicle_image
from matching.matcher import Matcher
from matching.models import MotorcycleQuery
from matching.review_policy import signature
from matching.rules import load_matching_rules
from partners.images import IMAGE_FIELDS
from scanner_base.normalizer import normalize_text
from services.refinement_service import diagnostics, probable_absence

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DashboardConfig:
    database: Path
    partner: str = "wr_motos"
    read_only: bool = False

    @classmethod
    def from_env(cls):
        return cls(
            Path(os.environ.get("MOTO_DB", "data/coverage.sqlite3")),
            os.environ.get("MOTO_PARTNER", "wr_motos"),
            os.environ.get("MOTO_READ_ONLY", "0").lower() in {"1", "true", "yes"},
        )


def filter_rows(rows, filters=None, text="", sort="priority"):
    filters = filters or {}
    terms = normalize_text(text).split()
    fields = ("manufacturer", "model", "year", "external_id", "scanner_key", "partner", "version")
    result = [
        row
        for row in rows
        if all(not values or row.get(key) in values for key, values in filters.items())
        and all(term in normalize_text(" ".join(str(row.get(f) or "") for f in fields)) for term in terms)
    ]
    keys = {
        "priority": lambda r: ({"high": 0, "medium": 1, "low": 2}.get(r.get("priority"), 3), r.get("id") or 0),
        "recent": lambda r: r.get("last_seen") or "",
        "oldest": lambda r: r.get("last_seen") or "",
        "model": lambda r: (r.get("manufacturer") or "", r.get("model") or ""),
    }
    return sorted(result, key=keys[sort], reverse=sort == "recent")


def flat(ad, automatic, effective, review=None, base=None):
    target = base.get(effective.get("scanner_key")) if base else None
    return {
        "id": review["id"] if review else None,
        "external_id": ad["external_id"],
        "partner": ad["partner"],
        "manufacturer": ad.get("manufacturer"),
        "model": ad.get("model"),
        "version": ad.get("version"),
        "year": ad.get("year"),
        "price": ad.get("price"),
        "mileage": ad.get("mileage"),
        "source_url": ad.get("source_url"),
        **{key: ad.get(key) for key in IMAGE_FIELDS},
        "first_seen": ad.get("first_seen") or (review.get("created_at") if review else ad.get("collected_at")),
        "last_seen": ad.get("last_seen") or (review["last_seen"] if review else ad.get("collected_at")),
        "automatic_type": automatic["match_type"],
        "score": automatic.get("confidence"),
        "effective_type": effective["match_type"],
        "scanner_key": effective.get("scanner_key"),
        "coverage": effective.get("scanner_status"),
        "state": review["state"] if review else None,
        "priority": review["priority"] if review else None,
        "supported_systems": target.supported_systems if target else [],
        "unsupported_systems": target.unsupported_systems if target else [],
        "analysis_systems": target.analysis_systems if target else [],
        "unknown_systems": target.unknown_systems if target else [],
    }


def unknown():
    return {
        "match_type": "AGUARDANDO_MATCHING",
        "scanner_key": None,
        "scanner_status": None,
        "confidence": None,
        "requires_review": True,
        "candidates": [],
    }


class DashboardService:
    def __init__(self, config):
        self.config = config

    def image_metadata(self, ad):
        with DashboardRepository(self.config.database) as repo:
            return latest_vehicle_image(repo.connection, ad)

    def snapshot(self):
        with DashboardRepository(self.config.database) as repo:
            items = repo.queue(self.config.partner)
            ads = repo.advertisements(self.config.partner)
            by_ad = {i["external_id"]: i for i in items}
            coverage = repo.automatic_coverage({a["collection_id"] for a in ads})
            stock = []
            for ad in ads:
                review = by_ad.get(ad["external_id"])
                if review and review["signature"] == signature(ad):
                    auto, effective = review["automatic"], review["effective"]
                else:
                    saved = coverage.get((ad["collection_id"], ad["external_id"]))
                    auto = saved["result"] if saved and saved["base_id"] == repo.base_id else unknown()
                    effective = auto
                    review = None
                stock.append(flat(ad, auto, effective, review, repo.base))
            queue = [flat(i["advertisement"], i["automatic"], i["effective"], i, repo.base) for i in items]
            collections = repo.collections(self.config.partner, 1)
            latest = collections[0] if collections else None
            if latest:
                latest["delta"] = repo.collection_delta(latest["id"], self.config.partner)
                latest["warnings"] = repo.collection_warnings(latest["id"])
            return {
                "partner": self.config.partner,
                "partners": repo.partners(),
                "base_id": repo.base_id,
                "stock": stock,
                "queue": queue,
                "latest": latest,
                "matching": dict(Counter(r["automatic_type"] for r in stock)),
                "coverage": dict(
                    Counter(
                        r["coverage"]
                        or (
                            r["effective_type"]
                            if r["effective_type"] == "CONFIRMADO_AUSENTE_NA_BASE"
                            else "IDENTIDADE_PENDENTE"
                        )
                        for r in stock
                    )
                ),
                "states": dict(Counter(r["state"] for r in queue)),
                "priorities": dict(Counter(r["priority"] for r in queue if r["state"] in {"pending", "invalidated"})),
                "zero_km_warning": any("FILTROS_ZERO_KM_CONFLITANTES" in a.get("parse_warnings", []) for a in ads),
            }

    def detail(self, item_id):
        with DashboardRepository(self.config.database) as repo:
            item = repo.detail(item_id, self.config.partner)
            current_candidates = [
                asdict(m)
                for m in repo.motos
                if m.year == item["identity"]["year"]
                and m.manufacturer
                == repo.scanner_policy["manufacturer_aliases"].get(
                    item["identity"]["manufacturer"], item["identity"]["manufacturer"]
                )
            ]
            item["selectable_candidates"] = current_candidates
            return item

    def scanner(self, text=""):
        with DashboardRepository(self.config.database) as repo:
            rows = [{**asdict(m), "scanner_key": m.key} for m in repo.motos]
        return filter_rows(rows, text=text, sort="model")

    def search(self, text):
        snapshot = self.snapshot()
        return {
            "Anúncios": filter_rows(snapshot["stock"], text=text),
            "Fila": filter_rows(snapshot["queue"], text=text),
            "Scanner": self.scanner(text),
        }

    def opportunities(self):
        snapshot = self.snapshot()
        confirmed, probable, pending = [], [], []
        with DashboardRepository(self.config.database) as repo:
            engine = Matcher(repo.motos, repo.scanner_policy["manufacturer_aliases"], load_matching_rules())
            ads = {a["external_id"]: a for a in repo.advertisements(self.config.partner)}
            for row in snapshot["stock"]:
                if row["effective_type"] == "CONFIRMADO_AUSENTE_NA_BASE":
                    confirmed.append(row)
                    continue
                ad = ads[row["external_id"]]
                reason = None
                if row["effective_type"] == "NAO_ENCONTRADA_NA_BASE":
                    query = MotorcycleQuery(
                        ad["manufacturer"] or "", ad["model"] or "", ad["year"], ad.get("version") or ""
                    )
                    reason = probable_absence(ad, {"match_type": row["effective_type"]}, diagnostics(query, engine))
                if reason:
                    probable.append({**row, "evidence": reason})
                elif row["state"] in {"pending", "invalidated"} and row["priority"] == "high":
                    pending.append(row)
        return {"Confirmado ausente": confirmed, "Provável ausência": probable, "Ainda em revisão": pending}

    def history(self, page=0):
        with DashboardRepository(self.config.database) as repo:
            collections = repo.collections(self.config.partner, 30, page * 30)
            for collection in collections:
                collection["delta"] = repo.collection_delta(collection["id"], self.config.partner)
            return {"collections": collections, **repo.history(self.config.partner, 30, page * 30)}

    def submit(self, item_id, action, reviewer, note, candidate_key, submission_id, revision):
        if self.config.read_only:
            raise ValueError("Dashboard em modo somente leitura")
        if not submission_id or not revision:
            raise ValueError("Submissão sem identificador ou versão do item")
        try:
            with ReviewRepository(self.config.database) as repo:
                if repo._item(item_id)["partner"] != self.config.partner:
                    raise ValueError("Item não pertence ao parceiro selecionado")
                return repo.decide(
                    item_id,
                    action,
                    reviewer,
                    note,
                    candidate_key,
                    submission_id=submission_id,
                    expected_revision=revision,
                )
        except Exception:
            LOGGER.exception("dashboard_decision_failed item_id=%s", item_id)
            raise
