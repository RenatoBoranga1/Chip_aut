"""Explicit staging, optimistic transactional publication and recoverable derived work."""

import json
import logging
from dataclasses import asdict
from pathlib import Path, PureWindowsPath

from database.repository import encode
from database.scanner_repository import (
    ScannerRepository,
    active_import,
    decision_token,
    detail,
    event,
    impacts,
    overview,
    records,
    snapshot,
)
from database.transaction import atomic_database
from services.scanner_validation import config, differences, unpack, validate_upload
from services.scheduler_config import utcnow

LOGGER = logging.getLogger(__name__)


class ScannerService:
    def __init__(self, database, read_only=False):
        self.database = Path(database)
        self.read_only = read_only
        self.settings = config()

    def writable(self):
        if self.read_only:
            raise ValueError("Modo somente leitura: operação desabilitada")
        if not self.settings["enabled"]:
            raise ValueError("Atualização da base desabilitada")

    def list(self, page=0):
        return overview(self.database, page)

    def detail(self, identifier, page=0, kind=None):
        return detail(self.database, identifier, page, kind)

    def validate(self, content, filename):
        return validate_upload(content, filename, self.settings)[2]

    def prepare(self, content, filename, actor, notes=""):
        self.writable()
        if not actor.strip() or len(actor) > 120 or len(notes) > 4000:
            raise ValueError("Informe responsável e observações válidos")
        base, rules, report, digest = validate_upload(content, filename, self.settings)
        with atomic_database(self.database), ScannerRepository(self.database) as repo:
            db = repo.connection
            previous = db.execute(
                "SELECT id FROM scanner_versions WHERE sha256=? ORDER BY id DESC LIMIT 1", (digest,)
            ).fetchone()
            if previous:
                return {"id": previous[0], "duplicate": True}
            cur = db.execute(
                "INSERT INTO scanner_versions(original_filename,sha256,imported_at,imported_by,status,total_records,valid_records,unique_vehicles,invalid_records,notes,content,payload_json,policy_json,report_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    PureWindowsPath(filename).name[:255],
                    digest,
                    utcnow().isoformat(),
                    actor.strip(),
                    "VALIDATED" if report["publishable"] else "REJECTED",
                    report["total_records"],
                    report["valid_records"],
                    report["unique_vehicles"],
                    report["invalid_records"],
                    notes,
                    content,
                    encode(asdict(base)),
                    encode(rules),
                    encode(report),
                ),
            )
            identifier = cur.lastrowid
            self._compare(db, identifier, base, report)
            event(db, identifier, actor, "PREPARED", notes, report)
        return {"id": identifier, "duplicate": False}

    def _compare(self, db, identifier, base, report):
        current = active_import(db)
        old = snapshot(db, current)
        new = {m.key: asdict(m) for m in base.motorcycles}
        summary, rows = differences(old, new, records(db, current), base.records)
        changed = {key for kind, key, _ in rows if kind in {"ADDED", "CHANGED"}}
        impact = impacts(db, new, changed)
        report = {
            **report,
            "comparison": summary,
            "review_affected": sum(k == "REVIEW" and r["reason"] not in {"VALID", "PENDING"} for k, _, r in impact),
            "development_affected": sum(k == "DEVELOPMENT" for k, _, _ in impact),
        }
        db.execute("DELETE FROM scanner_differences WHERE version_id=?", (identifier,))
        db.executemany(
            "INSERT INTO scanner_differences(version_id,kind,identity_key,payload_json) VALUES (?,?,?,?)",
            [(identifier, k, key, encode(r)) for k, key, r in rows],
        )
        db.execute("DELETE FROM scanner_impacts WHERE version_id=?", (identifier,))
        db.executemany(
            "INSERT INTO scanner_impacts(version_id,kind,entity_id,payload_json) VALUES (?,?,?,?)",
            [(identifier, k, i, encode(r)) for k, i, r in impact],
        )
        db.execute(
            "UPDATE scanner_versions SET parent_import_id=?,impact_token=?,report_json=? WHERE id=?",
            (current, decision_token(db), encode(report), identifier),
        )

    def compare(self, identifier, actor):
        self.writable()
        if not actor.strip():
            raise ValueError("Informe responsável")
        with atomic_database(self.database), ScannerRepository(self.database) as repo:
            row = repo.connection.execute(
                "SELECT payload_json,report_json,status FROM scanner_versions WHERE id=?", (identifier,)
            ).fetchone()
            if not row or row[2] != "VALIDATED":
                raise ValueError("Selecione uma versão validada e ainda não publicada")
            self._compare(repo.connection, identifier, unpack(json.loads(row[0])), json.loads(row[1]))
            event(repo.connection, identifier, actor, "COMPARED", "Comparação atualizada")
        return self.detail(identifier)

    def publish(self, identifier, actor, notes, confirmed=False, expected_parent=None, expected_token=None):
        self.writable()
        if confirmed is not True:
            raise ValueError("Confirmação explícita de publicação obrigatória")
        if not actor.strip() or not notes.strip() or len(actor) > 120 or len(notes) > 4000:
            raise ValueError("Informe responsável e justificativa")
        try:
            with atomic_database(self.database), ScannerRepository(self.database) as repo:
                db = repo.connection
                cur = db.execute("SELECT * FROM scanner_versions WHERE id=?", (identifier,))
                row = cur.fetchone()
                if not row:
                    raise ValueError("Versão não encontrada")
                value = dict(zip((c[0] for c in cur.description), row))
                if value["status"] != "VALIDATED":
                    raise ValueError("Versão não validada ou já publicada")
                if active_import(db) != value["parent_import_id"] or expected_parent != value["parent_import_id"]:
                    raise ValueError("A base ativa mudou. Atualize a comparação e confirme novamente")
                if decision_token(db) != value["impact_token"] or expected_token != value["impact_token"]:
                    raise ValueError("As decisões ou o desenvolvimento mudaram. Atualize a comparação")
                base, rules, report, digest = validate_upload(
                    value["content"], value["original_filename"], self.settings
                )
                if (
                    digest != value["sha256"]
                    or encode(rules) != value["policy_json"]
                    or encode(asdict(base)) != value["payload_json"]
                    or not report["publishable"]
                ):
                    raise ValueError("A preparação ou as regras mudaram; valide novamente o arquivo")
                import_id, _ = repo.save_import(
                    base, "scanner-version:" + str(identifier), digest, rules, report, prepared_version_id=identifier
                )
                event(
                    db,
                    identifier,
                    actor,
                    "PUBLISHED",
                    notes,
                    {
                        "previous_import": expected_parent,
                        "import_id": import_id,
                        "comparison": json.loads(value["report_json"]).get("comparison"),
                    },
                )
                db.execute("INSERT INTO scanner_jobs(version_id,import_id) VALUES (?,?)", (identifier, import_id))
                self._alerts(db, identifier, json.loads(value["report_json"]))
        except Exception:
            # Failure evidence lives in a separate transaction, without changing the active base.
            try:
                with atomic_database(self.database), ScannerRepository(self.database) as repo:
                    if repo.connection.execute("SELECT 1 FROM scanner_versions WHERE id=?", (identifier,)).fetchone():
                        event(
                            repo.connection,
                            identifier,
                            actor,
                            "PUBLICATION_FAILED",
                            "Publicação não confirmada; versão ativa preservada",
                        )
                        self._alert(
                            repo.connection,
                            identifier,
                            "SCANNER_FAILED",
                            "Falha na publicação",
                            "Confira a comparação e as validações antes de tentar novamente",
                        )
            except Exception:
                LOGGER.exception("scanner_failure_audit_failed")
            raise
        derived = self.resume(identifier)
        return {"version_id": identifier, "import_id": import_id, "derived": derived}

    def _alert(self, db, identifier, kind, title, message):
        from partners.registry import PartnerRegistry

        for partner in PartnerRegistry().list(enabled_only=True):
            db.execute(
                "INSERT OR IGNORE INTO scanner_alerts(version_id,partner,event_key,alert_type,title,message,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    identifier,
                    partner.partner_key,
                    f"{identifier}:{partner.partner_key}:{kind}",
                    kind,
                    title,
                    message,
                    utcnow().isoformat(),
                ),
            )

    def _alerts(self, db, identifier, report):
        diff = report["comparison"]
        self._alert(
            db,
            identifier,
            "SCANNER_PUBLISHED",
            "Nova versão da base publicada",
            f"{diff['added']} motos adicionadas; {diff['removed']} removidas; {diff['changed']} alteradas. Consulte os detalhes da versão.",
        )
        if report["review_affected"]:
            self._alert(
                db,
                identifier,
                "SCANNER_REVIEW",
                "Decisões humanas precisam de revalidação",
                f"{report['review_affected']} casos afetados; histórico anterior preservado.",
            )
        if report["development_affected"]:
            self._alert(
                db,
                identifier,
                "SCANNER_DEVELOPMENT",
                "Desenvolvimento possivelmente atendido",
                f"{report['development_affected']} itens para conferir; presença não confirma suporte.",
            )

    def resume(self, identifier):
        self.writable()
        try:
            with atomic_database(self.database), ScannerRepository(self.database) as repo:
                db = repo.connection
                job = db.execute(
                    "SELECT import_id,status FROM scanner_jobs WHERE version_id=?", (identifier,)
                ).fetchone()
                if not job:
                    raise ValueError("Publicação sem atualização pendente")
                if job[1] == "DONE":
                    return "DONE"
                if active_import(db) != job[0]:
                    db.execute(
                        "UPDATE scanner_jobs SET status='SUPERSEDED',message='Uma versão mais recente está ativa' WHERE version_id=?",
                        (identifier,),
                    )
                    return "SUPERSEDED"
                from services.scanner_refresh import refresh_operational

                refresh_operational(self.database)
                db.execute(
                    "UPDATE scanner_jobs SET status='DONE',attempts=attempts+1,message='' WHERE version_id=?",
                    (identifier,),
                )
                event(
                    db,
                    identifier,
                    "Sistema",
                    "DERIVED_UPDATED",
                    "Matching e revisão reavaliados com anúncios existentes",
                )
            from services.prioritization_service import safe_refresh

            safe_refresh(self.database, origin="scanner_publication")
            return "DONE"
        except Exception:
            LOGGER.exception("scanner_derived_update_failed")
            with atomic_database(self.database), ScannerRepository(self.database) as repo:
                repo.connection.execute(
                    "UPDATE scanner_jobs SET status='PENDING',attempts=attempts+1,message='Atualização derivada pendente; tente novamente' WHERE version_id=?",
                    (identifier,),
                )
            return "PENDING"
