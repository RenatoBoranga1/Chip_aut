"""Priority alerts use their own IDs; no synthetic collection or pipeline run."""

import json

from database.prioritization_repository import PrioritizationRepository, installed, reading
from database.transaction import atomic_database
from services.scheduler_config import utcnow

PREFIX = "priority:"


def read_priority_alerts(path, partner=None):
    with reading(path) as db:
        if not installed(db):
            return []
        result = []
        for row in db.execute(
            "SELECT a.*,c.partner,c.entity_id,p.payload_json FROM priority_alerts a JOIN priority_cases c ON c.id=a.case_id JOIN priority_assessments p ON p.id=a.assessment_id"
            + (" WHERE c.partner=?" if partner else ""),
            (partner,) if partner else (),
        ):
            r = dict(row)
            data = json.loads(r.pop("payload_json"))
            source = data["evidence"]
            r.update(
                id=PREFIX + str(r["id"]),
                severity="ALTA" if r["alert_type"] != "PRIORITY_OUTDATED" else "ATENCAO",
                manufacturer=source.get("manufacturer"),
                scanner_key=source.get("scanner_key"),
                external_id=r["entity_id"],
                review_item_id=source.get("review_item_id"),
                pipeline_run_id=None,
                collection_run_id=None,
                first_seen_at=r["created_at"],
                last_seen_at=r["created_at"],
                occurrence_count=1,
                condition_active=1,
                message="Sugestão de atenção operacional. Não confirma necessidade de desenvolvimento.",
                details={
                    "priority_case_id": r["case_id"],
                    "advertisement": source,
                    "matching": source.get("effective_type"),
                    "coverage": source.get("coverage"),
                },
                read_at=None,
                archived_at=None,
                resolved_at=None,
            )
            result.append(r)
        return result


def history(path, alert_id, partner):
    with reading(path) as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT h.* FROM priority_alert_history h JOIN priority_alerts a ON a.id=h.alert_id JOIN priority_cases c ON c.id=a.case_id WHERE a.id=? AND c.partner=? ORDER BY h.id",
                (int(alert_id.removeprefix(PREFIX)), partner),
            )
        ]


def transition(path, alert_id, target, partner):
    if target not in {"NOVO", "LIDO", "ARQUIVADO", "RESOLVIDO"}:
        raise ValueError("Situação inválida")
    identifier = int(alert_id.removeprefix(PREFIX))
    with atomic_database(path), PrioritizationRepository(path) as repo:
        row = repo.connection.execute(
            "SELECT a.status FROM priority_alerts a JOIN priority_cases c ON c.id=a.case_id WHERE a.id=? AND c.partner=?",
            (identifier, partner),
        ).fetchone()
        if not row:
            raise ValueError("Alerta não encontrado para este parceiro")
        before = row[0]
        if before == target:
            return
        if before in {"ARQUIVADO", "RESOLVIDO"} and target == "LIDO":
            raise ValueError("Reabra o alerta antes de marcar como lido")
        repo.connection.execute("UPDATE priority_alerts SET status=? WHERE id=?", (target, identifier))
        repo.connection.execute(
            "INSERT INTO priority_alert_history(alert_id,created_at,action,before_status,after_status) VALUES (?,?,?,?,?)",
            (
                identifier,
                utcnow().isoformat(),
                {"NOVO": "REABERTO", "LIDO": "LIDO", "ARQUIVADO": "ARQUIVADO", "RESOLVIDO": "RESOLVIDO"}[target],
                before,
                target,
            ),
        )
