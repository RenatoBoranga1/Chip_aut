"""Motonil observations are never motorcycle classifications. Humans own acceptance."""

import hashlib
import json
from pathlib import Path

from database.inventory_repository import alert, event, now
from database.partner_repository import PartnerRepository
from database.repository import encode
from database.transaction import atomic_database
from partners.diagnostics import diagnose
from services.partner_inventory_import import clean_row, publish_rows, writable
from services.pipeline_lock import ExecutionLock

CLASSES = {"PENDING_CLASSIFICATION", "MOTORCYCLE", "KART", "SERVICE", "OTHER", "UNKNOWN"}


def identity_stamp(payload):
    return hashlib.sha256(
        encode([payload.get(k) for k in ("title", "source_url", "source_category")]).encode()
    ).hexdigest()


def withdraw(db, external_id, reason):
    db.execute(
        "UPDATE partner_advertisements SET not_seen_in_latest_collection=1 WHERE partner='motonil' AND external_id=?",
        (external_id,),
    )
    for identifier, import_id in db.execute(
        "SELECT id,evaluated_import_id FROM review_items WHERE partner='motonil' AND external_id=? AND active=1",
        (external_id,),
    ).fetchall():
        db.execute("UPDATE review_items SET active=0,state='invalidated',updated_at=? WHERE id=?", (now(), identifier))
        db.execute(
            "INSERT INTO review_events(review_item_id,created_at,import_id,reason) VALUES (?,?,?,?)",
            (identifier, now(), import_id, reason),
        )


class MotonilStagingService:
    def __init__(self, database, *, read_only=False, reports=None):
        self.database = Path(database)
        self.read_only = read_only
        self.reports = Path(reports or self.database.parent / "partner-import-reports")

    def collect(self, *, reader=None, sleeper=None):
        writable(self.database, self.read_only)
        kwargs = {"live": True, "reader": reader}
        if sleeper is not None:
            kwargs["sleeper"] = sleeper
        diagnostic = diagnose("motonil", **kwargs)
        if diagnostic.get("error") or diagnostic.get("structure_changed") or not diagnostic.get("items"):
            with PartnerRepository(self.database) as repo, repo.connection:
                event(
                    repo.connection,
                    "motonil",
                    "STAGING_FAILED",
                    "sistema",
                    {"codes": diagnostic.get("warning_codes", [])},
                )
                alert(repo.connection, "motonil", "SOURCE_UNAVAILABLE")
            raise ValueError("Coleta de triagem indisponível; registros anteriores preservados")
        result = self.stage(diagnostic["items"])
        result["partial"] = diagnostic.get("partial", True)
        return result

    def stage(self, items):
        writable(self.database, self.read_only)
        if not items or len(items) > 500:
            raise ValueError("Lote de triagem vazio ou maior que 500 itens")
        items = [dict(i) for i in items]
        for item in items:
            if not item.get("external_id"):
                from partners.sources import public_url

                url = public_url(item.get("source_url") or "")
                item["external_id"] = "url:" + hashlib.sha256(url.encode()).hexdigest()
        ids = [str(i.get("external_id", "")) for i in items]
        if not all(ids) or len(set(ids)) != len(ids):
            raise ValueError("IDs vazios ou duplicados na triagem")
        accepted = []
        reused = 0
        with (
            ExecutionLock(self.database, partner="motonil"),
            atomic_database(self.database),
            PartnerRepository(self.database) as repo,
        ):
            db = repo.connection
            for item in items:
                payload = {
                    k: item.get(k) for k in ("external_id", "title", "source_url", "source_category", "image_url")
                }
                from urllib.parse import urlsplit

                url = urlsplit(payload.get("source_url") or "")
                if url.scheme != "https" or url.hostname != "www.motonil.com.br" or url.username or url.password:
                    raise ValueError("Origem inválida do item Motonil")
                external_id = str(payload["external_id"])
                sig = identity_stamp(payload)
                stamp = now()
                prior = db.execute(
                    "SELECT signature,classification,identity_json,revision FROM partner_staging WHERE partner='motonil' AND external_id=?",
                    (external_id,),
                ).fetchone()
                if not prior:
                    db.execute(
                        "INSERT INTO partner_staging VALUES ('motonil',?,?,?,?,?,'PENDING_CLASSIFICATION',1,'{}')",
                        (external_id, sig, encode(payload), stamp, stamp),
                    )
                    event(db, "motonil", "TRIAGE_CREATED", "sistema", {"reason": "Novo item"}, external_id)
                elif prior[0] != sig:
                    withdraw(db, external_id, "Identidade mudou na triagem Motonil; exige nova classificação humana")
                    db.execute(
                        "UPDATE partner_staging SET signature=?,payload_json=?,last_seen=?,classification='PENDING_CLASSIFICATION',identity_json='{}',revision=revision+1 WHERE partner='motonil' AND external_id=?",
                        (sig, encode(payload), stamp, external_id),
                    )
                    event(
                        db,
                        "motonil",
                        "TRIAGE_INVALIDATED",
                        "sistema",
                        {"previous_classification": prior[1]},
                        external_id,
                    )
                else:
                    db.execute(
                        "UPDATE partner_staging SET last_seen=?,payload_json=? WHERE partner='motonil' AND external_id=?",
                        (stamp, encode(payload), external_id),
                    )
                    reused += prior[1] in {"MOTORCYCLE", "KART", "SERVICE", "OTHER"}
                    if prior[1] == "MOTORCYCLE":
                        accepted.append(json.loads(prior[2]))
            if accepted:
                publish_rows(
                    self.database, "motonil", accepted, False, "STAGED_COLLECTION / memória humana", self.reports
                )
            self.pending(db)
            alert(db, "motonil", "SOURCE_UNAVAILABLE", False)
            event(
                db,
                "motonil",
                "STAGING_COLLECTED",
                "sistema",
                {"observed": len(items), "accepted_from_memory": len(accepted), "reused_decisions": reused},
            )
        self.refresh()
        return {
            "staged": len(items),
            "accepted_from_memory": len(accepted),
            "reused_decisions": reused,
            "published_automatically_unknown": 0,
        }

    @staticmethod
    def pending(db):
        # M15 maintains PARTNER_TRIAGE_PENDING after commit. Resolve its legacy
        # counterpart so the same pending work never appears as two active alerts.
        alert(db, "motonil", "TRIAGE_PENDING", False)

    def classify(self, external_id, classification, *, reviewer, note, expected_revision, identity=None):
        if not note.strip():
            raise ValueError("Informe classificação, responsável e justificativa")
        self.classify_batch(
            [
                {
                    "partner": "motonil",
                    "external_id": str(external_id),
                    "revision": expected_revision,
                    "identity": identity or {},
                }
            ],
            classification,
            reviewer=reviewer,
            note=note,
            confirmed=True,
        )
        return {"external_id": str(external_id), "classification": classification, "revision": expected_revision + 1}

    def classify_batch(self, selections, classification, *, reviewer, note="", confirmed=False):
        writable(self.database, self.read_only)
        if not confirmed or not reviewer.strip() or classification not in CLASSES - {"PENDING_CLASSIFICATION"}:
            raise ValueError("Confirme o lote, a classificação e o responsável")
        if not selections or len(selections) > 100:
            raise ValueError("Selecione de 1 a 100 itens")
        ids = [str(s.get("external_id", "")) for s in selections]
        if len(set(ids)) != len(ids) or not all(ids) or any(s.get("partner") != "motonil" for s in selections):
            raise ValueError("Lote deve conter itens distintos somente da Motonil")
        accepted = []
        with (
            ExecutionLock(self.database, partner="motonil"),
            atomic_database(self.database),
            PartnerRepository(self.database) as repo,
        ):
            db = repo.connection
            # Validate every revision and every motorcycle before any publication.
            changes = []
            for selection in selections:
                identifier = str(selection["external_id"])
                prior = db.execute(
                    "SELECT classification,revision,payload_json FROM partner_staging WHERE partner='motonil' AND external_id=?",
                    (identifier,),
                ).fetchone()
                if prior is None or prior[1] != selection.get("revision"):
                    raise ValueError("Item mudou; atualize a tela antes de classificar o lote")
                row = {}
                if classification == "MOTORCYCLE":
                    payload = json.loads(prior[2])
                    row, errors = clean_row(
                        {
                            **selection.get("identity", {}),
                            "external_id": identifier,
                            "detail_url": payload["source_url"],
                        }
                    )
                    if errors:
                        raise ValueError("; ".join(errors))
                    accepted.append(row)
                changes.append((identifier, prior[0], row))
            if accepted:
                publish_rows(
                    self.database, "motonil", accepted, False, "STAGED_COLLECTION / confirmação humana", self.reports
                )
            for identifier, previous, row in changes:
                if classification != "MOTORCYCLE":
                    withdraw(db, identifier, "Classificação humana alterada: " + classification)
                db.execute(
                    "UPDATE partner_staging SET classification=?,identity_json=?,revision=revision+1 WHERE partner='motonil' AND external_id=?",
                    (classification, encode(row), identifier),
                )
                event(
                    db,
                    "motonil",
                    "TRIAGE_CLASSIFIED",
                    reviewer,
                    {"from": previous, "to": classification, "note": note[:2000], "identity": row},
                    identifier,
                )
                event(
                    db,
                    "motonil",
                    "TRIAGE_RESOLVED",
                    reviewer,
                    {"from": previous, "to": classification, "batch_size": len(changes)},
                    identifier,
                )
            self.pending(db)
        self.refresh()
        return {"classified": len(selections), "classification": classification}

    def refresh(self):
        from services.prioritization_service import safe_refresh

        safe_refresh(self.database, "motonil", "collection")
        from services.partner_health_service import refresh_health

        refresh_health(self.database)
