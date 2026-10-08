"""Saved source evidence and offline validation. Never registers or enables an adapter."""

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

KINDS = {"HTML", "PUBLIC_API", "PUBLIC_JSON", "SITEMAP", "FEED", "OFFICIAL_MARKETPLACE"}
TRUST = {"OFFICIAL_DIRECT", "OFFICIAL_PROVIDER", "PUBLIC_STRUCTURED", "UNVERIFIED"}
STATES = {"INVESTIGATING", "BLOCKED", "REJECTED", "APPROVED", "DEGRADED"}
ALERTS = {
    "SOURCE_UNAVAILABLE": "Fonte indisponível; coleta suspensa.",
    "SOURCE_STRUCTURE_CHANGED": "Estrutura da fonte mudou; coleta suspensa.",
    "TYPE_CLASSIFICATION_UNAVAILABLE": "Tipo individual não comprovado; itens permanecem desconhecidos.",
    "ALTERNATIVE_SOURCE_FAILED": "Fonte alternativa reprovada; parceiro permanece fora da coleta.",
}


def public_url(url):
    """Metadata must never contain credentials, session URLs or non-HTTP targets."""
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError("URL pública inválida")
    if any(re.search(r"token|secret|password|senha|auth|cookie|api.?key", key, re.I) for key, _ in parse_qsl(p.query)):
        raise ValueError("Credencial não pode fazer parte da fonte")
    return url


@dataclass(frozen=True)
class PartnerSource:
    partner: str
    source_id: str
    source_kind: str
    source_url: str
    source_provider: str
    source_last_validated_at: str
    trust: str
    status: str
    access: str
    classification: str
    identity: str
    fields: tuple[str, ...]
    evidence: tuple[str, ...]
    reason: str
    warning_codes: tuple[str, ...] = ()
    observed_items: int | None = None
    unknown: int | None = None
    audited_sample: int = 0
    false_positives: int | None = None

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.partner) or not re.fullmatch(r"[a-z][a-z0-9_]*", self.source_id):
            raise ValueError("Identificador de fonte inválido")
        if self.source_kind not in KINDS or self.trust not in TRUST or self.status not in STATES:
            raise ValueError("Categoria de fonte inválida")
        date.fromisoformat(self.source_last_validated_at)
        for value in (self.observed_items, self.unknown, self.audited_sample, self.false_positives):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Contagem de evidência inválida")
        public_url(self.source_url)
        for link in self.evidence:
            public_url(link)
        if any(code not in ALERTS for code in self.warning_codes):
            raise ValueError("Aviso de fonte inválido")
        if self.status == "APPROVED" and not (
            self.trust != "UNVERIFIED"
            and self.access == "PUBLIC_ALLOWED"
            and self.classification == "DETERMINISTIC"
            and self.identity == "VERIFIED"
            and 10 <= self.audited_sample <= 20
            and self.false_positives == 0
        ):
            raise ValueError("Fonte sem evidências suficientes para aprovação")


def load_sources(partner=None, path=None):
    path = path or Path(__file__).parents[1] / "config/partner_sources.json"
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    sources = []
    seen = set()
    for row in data["sources"]:
        source = PartnerSource(
            **{**row, **{key: tuple(row.get(key, [])) for key in ("fields", "evidence", "warning_codes")}}
        )
        key = (source.partner, source.source_id)
        if key in seen:
            raise ValueError("Fonte duplicada")
        seen.add(key)
        sources.append(source)
    if partner is not None and partner not in {s.partner for s in sources} | {"wr_motos"}:
        raise ValueError("Parceiro desconhecido")
    return [s for s in sources if partner is None or s.partner == partner]


def source_report(partner):
    return [asdict(s) for s in load_sources(partner)]


def source_notices(sources):
    """Deduplicated diagnostic notices, not repeated operational notification events."""
    unique = {}
    for source in sources:
        for code in source.warning_codes:
            unique[(source.partner, source.source_id, code)] = {
                "Parceiro": source.partner,
                "Fonte": source.source_id,
                "Código": code,
                "Aviso": ALERTS[code],
                "Validação": source.source_last_validated_at,
            }
    return list(unique.values())


def classify_record(record):
    """Only exact structural types; no title/brand/category-name heuristics."""
    values = [record[k] for k in ("vehicle_type", "item_type", "@type") if k in record]
    if not values or any(not isinstance(v, str) for v in values):
        return "UNKNOWN"
    mapping = {"motorcycle": "MOTORCYCLE", "car": "CAR", "kart": "KART", "service": "SERVICE"}
    types = {mapping.get(v.casefold(), "UNKNOWN") for v in values}
    return types.pop() if len(types) == 1 else "UNKNOWN"


def inspect_document(body, kind):
    """Offline structural probe; never fetches discovered URLs or accepts executable code.

    JSON/feed records use an explicit diagnostic contract, not a universal collector.
    Sitemap links provide discovery only. Product/Vehicle JSON-LD is not Motorcycle.
    """
    if len(body.encode("utf-8")) > 2_000_000:
        raise ValueError("Documento excede limite")
    if kind not in KINDS:
        raise ValueError("Formato não suportado")
    records, links = [], []
    if kind in {"PUBLIC_API", "PUBLIC_JSON"}:
        data = json.loads(body)
        records = data if isinstance(data, list) else data.get("items") if isinstance(data, dict) else None
    elif kind in {"SITEMAP", "FEED"}:
        if re.search(r"<!DOCTYPE|<!ENTITY", body, re.I):
            raise ValueError("Entidades XML não permitidas")
        root = ElementTree.fromstring(body)
        if kind == "SITEMAP":
            links = [public_url(e.text.strip()) for e in root.iter() if e.tag.rsplit("}", 1)[-1] == "loc" and e.text]
        else:
            records = [
                {e.tag.rsplit("}", 1)[-1]: e.text or "" for e in item}
                for item in root.iter()
                if item.tag.rsplit("}", 1)[-1] in {"item", "entry", "vehicle"}
            ]
    else:
        soup = BeautifulSoup(body, "html.parser")
        for script in soup.select('script[type="application/ld+json"]'):
            data = json.loads(script.get_text())
            nodes = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
            records.extend(nodes)
    if not isinstance(records, list) or len(records) > 500 or any(not isinstance(r, dict) for r in records):
        raise ValueError("Estrutura não reconhecida")
    return {"records": records, "discovery_urls": links, "publishable": False}


def audit_records(source, records, *, previously_approved=False):
    """Classify an offline sample, gate the whole batch, and explain every abstention.

    This is evidence only: even a valid batch cannot activate registry configuration.
    """
    started = time.perf_counter()
    if len(records) > 500:
        raise ValueError("Amostra excede limite")
    metrics = dict(
        raw_items=len(records), motorcycles=0, unknown=0, excluded=0, parse_errors=0, invalid_identity=0, duplicates=0
    )
    seen, items = set(), []
    for row in records:
        if not isinstance(row, dict):
            metrics["parse_errors"] += 1
            continue
        kind = classify_record(row)
        identifier = row.get("external_id") or row.get("id") or row.get("sku")
        identifier = (
            str(identifier).strip() if isinstance(identifier, (str, int)) and not isinstance(identifier, bool) else ""
        )
        valid = bool(
            identifier
            and row.get("manufacturer")
            and row.get("model")
            and re.fullmatch(r"\d{4}", str(row.get("year", "")))
        )
        try:
            public_url(row.get("detail_url", ""))
        except (ValueError, TypeError, AttributeError):
            valid = False
        duplicate = bool(identifier and identifier in seen)
        seen.add(identifier)
        metrics["duplicates"] += int(duplicate)
        metrics["invalid_identity"] += int(not valid)
        metrics["unknown"] += int(kind == "UNKNOWN")
        metrics["excluded"] += int(kind in {"CAR", "KART", "SERVICE"})
        metrics["motorcycles"] += int(kind == "MOTORCYCLE" and valid and not duplicate)
        reason = "DUPLICATE_ID" if duplicate else "INVALID_IDENTITY" if not valid else "TYPE_" + kind
        items.append({"external_id": identifier, "classification": kind, "reason": reason})
    errors = ["TYPE_CLASSIFICATION_UNAVAILABLE"] if metrics["unknown"] else []
    if metrics["parse_errors"] or metrics["invalid_identity"] or metrics["duplicates"] or not records:
        errors.append("SOURCE_STRUCTURE_CHANGED")
    eligible = source.status == "APPROVED" and not errors
    if source.status != "APPROVED":
        errors.append("ALTERNATIVE_SOURCE_FAILED")
    return {
        **metrics,
        "items": items,
        "warning_codes": sorted(set(errors)),
        "status": "VALIDATED" if eligible else "DEGRADED" if previously_approved else "BLOCKED",
        "eligible_batch": eligible,
        "publishable": False,
        "classification_seconds": time.perf_counter() - started,
    }


def dry_run(partner, *, reader=None, sleeper=time.sleep):
    """Reuse the bounded public diagnostic; never fetch candidate APIs or persist ads."""
    sources = load_sources(partner)
    if partner == "wr_motos":
        raise ValueError("WR mantém seu coletor existente; este comando avalia apenas fontes alternativas")
    from partners.diagnostics import diagnose

    started = time.perf_counter()
    diagnosis = diagnose(partner, live=True, reader=reader, sleeper=sleeper)
    return {
        "partner": partner,
        "dry_run": True,
        "status": "BLOCKED",
        "reason": "Nenhuma fonte alternativa aprovada. Diagnóstico limitado do catálogo permitido; sem publicação ou gravação.",
        "diagnosis": diagnosis,
        "sources": [asdict(s) for s in sources],
        "raw_items": diagnosis.get("observed_items"),
        "motorcycles": None,
        "unknown": diagnosis.get("unknown_items"),
        "excluded": None,
        "parse_errors": None,
        "invalid_identity": None,
        "duplicates": None,
        "collection_duration": time.perf_counter() - started,
        "publishable": False,
    }
