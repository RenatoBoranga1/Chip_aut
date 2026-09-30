"""Summary alerts for scanner publications; no fake collection rows."""

from database.development_repository import read_connection
from database.scanner_repository import ScannerRepository, installed
from database.transaction import atomic_database
from services.scheduler_config import utcnow


def read_scanner_alerts(path, partner=None):
    with read_connection(path) as db:
        if not installed(db):
            return []
        rows = db.execute(
            "SELECT * FROM scanner_alerts" + (" WHERE partner=?" if partner else ""), (partner,) if partner else ()
        )
        return [
            dict(r)
            | {
                "id": "scanner:" + str(r["id"]),
                "severity": "ATENCAO" if r["alert_type"] != "SCANNER_PUBLISHED" else "INFO",
                "manufacturer": None,
                "scanner_key": None,
                "external_id": None,
                "review_item_id": None,
                "pipeline_run_id": None,
                "collection_run_id": None,
                "first_seen_at": r["created_at"],
                "last_seen_at": r["created_at"],
                "occurrence_count": 1,
                "condition_active": 1,
                "details": {"scanner_version_id": r["version_id"]},
                "read_at": None,
                "archived_at": None,
                "resolved_at": None,
            }
            for r in rows
        ]


def history(path, alert_id, partner):
    with read_connection(path) as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT h.* FROM scanner_alert_history h JOIN scanner_alerts a ON a.id=h.alert_id WHERE a.id=? AND a.partner=? ORDER BY h.id",
                (int(alert_id.split(":")[1]), partner),
            )
        ]


def transition(path, alert_id, target, partner):
    if target not in {"NOVO", "LIDO", "ARQUIVADO", "RESOLVIDO"}:
        raise ValueError("Situação inválida")
    with atomic_database(path), ScannerRepository(path) as repo:
        db = repo.connection
        identifier = int(alert_id.split(":")[1])
        row = db.execute("SELECT status FROM scanner_alerts WHERE id=? AND partner=?", (identifier, partner)).fetchone()
        if not row:
            raise ValueError("Alerta não encontrado para este parceiro")
        if row[0] == target:
            return
        if row[0] in {"ARQUIVADO", "RESOLVIDO"} and target == "LIDO":
            raise ValueError("Reabra o alerta antes de marcar como lido")
        db.execute("UPDATE scanner_alerts SET status=? WHERE id=?", (target, identifier))
        db.execute(
            "INSERT INTO scanner_alert_history(alert_id,created_at,action,before_status,after_status) VALUES (?,?,?,?,?)",
            (identifier, utcnow().isoformat(), "REABERTO" if target == "NOVO" else target, row[0], target),
        )


def development_notice(path, item_id):
    with read_connection(path) as db:
        if not installed(db):
            return None
        row = db.execute(
            "SELECT v.id,i.payload_json FROM scanner_impacts i JOIN scanner_versions v ON v.id=i.version_id WHERE i.kind='DEVELOPMENT' AND i.entity_id=? AND v.import_id=(SELECT MAX(id) FROM imports) ORDER BY i.id DESC LIMIT 1",
            (item_id,),
        ).fetchone()
        return row[0] if row else None
