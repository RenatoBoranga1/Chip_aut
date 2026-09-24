"""Adapter for development notifications in the shared alert center."""

from database.development_repository import DevelopmentRepository, exists, read_connection
from database.transaction import atomic_database
from services.scheduler_config import utcnow


def read_development_alerts(database, partner=None):
    with read_connection(database) as db:
        if not exists(db):
            return []
        rows = db.execute(
            "SELECT a.*,d.manufacturer,d.scanner_key,d.model,d.year FROM development_alerts a JOIN development_items d ON d.id=a.item_id"
            + (
                " WHERE EXISTS(SELECT 1 FROM development_origins o WHERE o.item_id=d.id AND o.partner IN (?, 'scanner'))"
                if partner
                else ""
            ),
            (partner,) if partner else (),
        ).fetchall()
        result = []
        for row in rows:
            r = dict(row)
            # Negative IDs are an adapter namespace; persisted IDs stay positive in each table.
            r.update(
                id=-r["id"],
                partner=partner or "development",
                external_id=None,
                review_item_id=None,
                pipeline_run_id=None,
                collection_run_id=None,
                first_seen_at=r["created_at"],
                last_seen_at=r["created_at"],
                occurrence_count=1,
                condition_active=1,
                details={"development_item_id": r["item_id"]},
                read_at=None,
                archived_at=None,
                resolved_at=None,
            )
            result.append(r)
        return result


def development_alert_history(database, alert_id, partner):
    with read_connection(database) as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT h.* FROM development_alert_history h JOIN development_alerts a ON a.id=h.alert_id WHERE a.id=? AND EXISTS(SELECT 1 FROM development_origins o WHERE o.item_id=a.item_id AND o.partner IN (?, 'scanner')) ORDER BY h.id",
                (abs(alert_id), partner),
            )
        ]


def transition_alert(database, alert_id, target, partner):
    if target not in {"NOVO", "LIDO", "ARQUIVADO", "RESOLVIDO"}:
        raise ValueError("Situação do alerta inválida")
    with atomic_database(database), DevelopmentRepository(database) as repo:
        row = repo.connection.execute(
            "SELECT a.status FROM development_alerts a WHERE a.id=? AND EXISTS(SELECT 1 FROM development_origins o WHERE o.item_id=a.item_id AND o.partner IN (?, 'scanner'))",
            (abs(alert_id), partner),
        ).fetchone()
        if not row:
            raise ValueError("Alerta não encontrado para este parceiro")
        before = row[0]
        if target == before:
            return
        if before in {"ARQUIVADO", "RESOLVIDO"} and target == "LIDO":
            raise ValueError("Reabra o alerta antes de marcar como lido")
        stamp = utcnow().isoformat()
        action = {
            "NOVO": "REABERTO" if before in {"ARQUIVADO", "RESOLVIDO"} else "NAO_LIDO",
            "LIDO": "LIDO",
            "ARQUIVADO": "ARQUIVADO",
            "RESOLVIDO": "RESOLVIDO",
        }[target]
        repo.connection.execute(
            "UPDATE development_alerts SET status=?,updated_at=? WHERE id=?", (target, stamp, abs(alert_id))
        )
        repo.connection.execute(
            "INSERT INTO development_alert_history(alert_id,created_at,action,before_status,after_status) VALUES (?,?,?,?,?)",
            (abs(alert_id), stamp, action, before, target),
        )
