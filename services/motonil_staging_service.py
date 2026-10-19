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
        ids = [str(i.get("external_id", "")) for i in items]
        if not all(ids) or len(set(ids)) != len(ids):
            raise ValueError("IDs vazios ou duplicados na triagem")
        accepted = []
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
                {"observed": len(items), "accepted_from_memory": len(accepted)},
            )
        self.refresh()
        return {"staged": len(items), "accepted_from_memory": len(accepted), "published_automatically_unknown": 0}

    @staticmethod
    def pending(db):
        count = db.execute(
            "SELECT count(*) FROM partner_staging WHERE classification IN ('PENDING_CLASSIFICATION','UNKNOWN')"
        ).fetchone()[0]
        alert(db, "motonil", "TRIAGE_PENDING", bool(count))

    def classify(self, external_id, classification, *, reviewer, note, expected_revision, identity=None):
        writable(self.database, self.read_only)
        if classification not in CLASSES - {"PENDING_CLASSIFICATION"} or not reviewer.strip() or not note.strip():
            raise ValueError("Informe classificação, responsável e justificativa")
        with (
            ExecutionLock(self.database, partner="motonil"),
            atomic_database(self.database),
            PartnerRepository(self.database) as repo,
        ):
            db = repo.connection
            prior = db.execute(
                "SELECT classification,revision,payload_json FROM partner_staging WHERE partner='motonil' AND external_id=?",
                (str(external_id),),
            ).fetchone()
            if prior is None or prior[1] != expected_revision:
                raise ValueError("Item mudou; atualize a tela antes de classificar")
            payload = json.loads(prior[2])
            row = {}
            if classification == "MOTORCYCLE":
                row, errors = clean_row(
                    {**(identity or {}), "external_id": str(external_id), "detail_url": payload["source_url"]}
                )
                if errors:
                    raise ValueError("; ".join(errors))
                publish_rows(
                    self.database, "motonil", [row], False, "STAGED_COLLECTION / confirmação humana", self.reports
                )
            else:
                withdraw(db, str(external_id), "Classificação humana alterada: " + classification)
            db.execute(
                "UPDATE partner_staging SET classification=?,identity_json=?,revision=revision+1 WHERE partner='motonil' AND external_id=?",
                (classification, encode(row), str(external_id)),
            )
            event(
                db,
                "motonil",
                "TRIAGE_CLASSIFIED",
                reviewer,
                {"from": prior[0], "to": classification, "note": note, "identity": row},
                str(external_id),
            )
            self.pending(db)
        self.refresh()
        return {"external_id": str(external_id), "classification": classification, "revision": expected_revision + 1}

    def refresh(self):
        from services.prioritization_service import safe_refresh

        safe_refresh(self.database, "motonil", "collection")
