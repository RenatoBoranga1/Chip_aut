"""Explicit, audited development commands. Completion never changes scanner coverage."""

import hashlib
import sqlite3
from dataclasses import asdict
from datetime import date, datetime

from database.dashboard_repository import DashboardRepository
from database.development_repository import DevelopmentRepository, find_active, list_items, read_item, source_snapshot
from database.repository import encode
from database.transaction import atomic_database
from matching.fuzzy_matcher import combined_model
from matching.review_policy import complete_identity, identity
from scanner_base.normalizer import normalize_model, normalize_text
from services.development_policy import (
    CLOSED,
    PRIORITIES,
    TECHNICAL,
    TRANSITIONS,
    load_development_config,
)
from services.scheduler_config import utcnow


def required(text, label, limit=4000):
    if not isinstance(text, str) or not text.strip() or len(text) > limit:
        raise ValueError(f"Informe {label} válido (até {limit} caracteres)")
    return text.strip()


def identity_key(source):
    ad = source["advertisement"]
    target = source.get("scanner")
    value = identity({**ad, **({k: target[k] for k in ("manufacturer", "model", "year")} if target else {})})
    value.pop("partner")
    if not complete_identity(value):
        raise ValueError("Identidade incompleta: confirme fabricante, modelo e ano antes de incluir")
    if source["effective"].get("match_type") in {
        "AMBIGUOUS",
        "REVISAR",
        "CORRESPONDENCIA_PROVAVEL",
        "AGUARDANDO_MATCHING",
    } or set(ad.get("parse_warnings", [])) - {"FILTROS_ZERO_KM_CONFLITANTES"}:
        # An unresolved trim or malformed title must not merge different advertisements.
        value["origin_scope"] = [ad["partner"], ad["external_id"]]
    return hashlib.sha256(encode(value).encode()).hexdigest(), value


def allowed_reasons(source):
    effective = source["effective"]
    reasons = ["MANUAL"]
    if effective.get("match_type") == "CONFIRMADO_AUSENTE_NA_BASE":
        reasons.append("CONFIRMED_MISSING")
    if source.get("scanner"):
        if source["scanner"]["status"] == "SEM_SUPORTE":
            reasons.append("UNSUPPORTED")
        elif source["scanner"]["status"] == "SUPORTE_PARCIAL":
            reasons.append("PARTIAL_SUPPORT")
    if source.get("priority") == "high" and source.get("review_item_id"):
        reasons.append("HIGH_PRIORITY_REVIEW")
    if effective.get("match_type") in {"NAO_ENCONTRADA_NA_BASE", "CONFIRMADO_AUSENTE_NA_BASE"}:
        reasons.append("NEW_MODEL")
    return reasons


class DevelopmentService:
    def __init__(self, config, policy=None, clock=utcnow):
        self.config = config
        self.policy = policy if policy is not None else load_development_config()
        self.clock = clock

    def writable(self):
        if self.config.read_only:
            raise ValueError("Modo somente leitura: alterações desabilitadas")
        if not self.policy["enabled"]:
            raise ValueError("Gestão de desenvolvimento desabilitada")

    def source(self, kind, identifier):
        value = source_snapshot(self.config.database, self.config.partner, kind, identifier)
        value["reference"] = {"kind": kind, "id": str(identifier), "partner": self.config.partner}
        return value

    def existing(self, kind, identifier):
        return find_active(self.config.database, identity_key(self.source(kind, identifier))[0])

    def assignee(self, value):
        if not isinstance(value, str) or len(value) > 120:
            raise ValueError("Responsável inválido")
        value = value.strip()
        if value and self.policy["assignees"] and value not in self.policy["assignees"]:
            raise ValueError("Responsável fora da lista configurada")
        return value

    def create(
        self,
        kind,
        identifier,
        *,
        actor,
        justification,
        reason,
        command_key,
        confirmed=False,
        priority=None,
        assigned_to="",
    ):
        self.writable()
        if confirmed is not True:
            raise ValueError("Confirme explicitamente a inclusão para desenvolvimento")
        actor, note = required(actor, "autor", 120), required(justification, "justificativa")
        command_key = required(command_key, "identificador da solicitação", 200)
        assigned_to = self.assignee(assigned_to)
        payload = encode(
            ["create", self.config.partner, kind, str(identifier), actor, note, reason, priority, assigned_to]
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with atomic_database(self.config.database), DevelopmentRepository(self.config.database) as repo:
            replay = repo.replay(command_key, digest)
            if replay:
                return replay
            source = self.source(kind, identifier)
            if reason not in allowed_reasons(source):
                raise ValueError("Motivo sem evidência atual; revise o caso ou use inclusão manual justificada")
            key, ident = identity_key(source)
            selected_priority = priority or source["priority"] or "medium"
            if selected_priority not in PRIORITIES:
                raise ValueError("Prioridade inválida")
            stamp = self.clock().isoformat()
            ad = source["advertisement"]
            item_id = repo.active(key)
            if item_id is None:
                item_id = repo.insert(
                    {
                        "identity_key": key,
                        "identity_json": encode(ident),
                        "manufacturer": ad["manufacturer"],
                        "model": ad["model"],
                        "version": ad.get("version"),
                        "year": ad["year"],
                        "scanner_key": source["scanner"]["key"] if source["scanner"] else None,
                        "base_version": source["base_version"],
                        "source_json": encode(source),
                        "reason": reason,
                        "priority": selected_priority,
                        "assigned_to": assigned_to,
                        "created_by": actor,
                        "created_at": stamp,
                        "updated_at": stamp,
                        "status_since": stamp,
                        "first_seen_at": ad.get("first_seen") or ad.get("collected_at") or stamp,
                        "last_seen_at": ad.get("last_seen") or ad.get("collected_at") or stamp,
                        "primary_image_url": ad.get("primary_image_url"),
                        "checklist_json": encode(
                            {k: {"label": v, "done": False} for k, v in self.policy["checklist"].items()}
                        ),
                    }
                )
                repo.event(
                    item_id,
                    actor,
                    "CREATE",
                    {},
                    {
                        "status": "NEW",
                        "priority": selected_priority,
                        "assigned_to": assigned_to,
                        "reason": reason,
                        "source": source,
                    },
                    note,
                    stamp,
                )
                if selected_priority == "high":
                    self.notify(
                        repo,
                        item_id,
                        "DEV_NEW",
                        f"new:{item_id}",
                        "ALTA",
                        "Novo item de desenvolvimento de alta prioridade",
                        note,
                        stamp,
                    )
            if repo.origin(item_id, source, actor, stamp):
                repo.event(item_id, actor, "ORIGIN", {}, source, note, stamp)
            repo.remember(command_key, digest, item_id)
            return item_id

    def notify(self, repo, item_id, kind, key, severity, title, message, stamp):
        if self.policy["alerts_enabled"]:
            repo.notify(item_id, kind, key, severity, title, message, stamp)

    def change(
        self, item_id, action, value, *, actor, justification, command_key, expected_revision, completion_version=None
    ):
        self.writable()
        actor, note = required(actor, "autor", 120), required(justification, "justificativa")
        command_key = required(command_key, "identificador da solicitação", 200)
        payload = encode([item_id, action, value, actor, note, expected_revision, completion_version])
        digest = hashlib.sha256(payload.encode()).hexdigest()
        try:
            with atomic_database(self.config.database), DevelopmentRepository(self.config.database) as repo:
                replay = repo.replay(command_key, digest)
                if replay:
                    if replay != item_id:
                        raise ValueError("Solicitação pertence a outro item")
                    return replay
                item = repo.one(item_id)
                if type(expected_revision) is not int or expected_revision != item["revision"]:
                    raise ValueError("Item alterado por outra operação; atualize antes de salvar")
                stamp = self.clock().isoformat()
                updates, before, after = {}, {}, {}
                if action == "status":
                    if value not in TRANSITIONS[item["status"]]:
                        raise ValueError("Transição de situação não permitida")
                    if value == "COMPLETED" and not item["assigned_to"]:
                        raise ValueError("Atribua um responsável antes de concluir")
                    if completion_version is not None and (
                        not isinstance(completion_version, str) or len(completion_version) > 120
                    ):
                        raise ValueError("Versão de conclusão inválida")
                    updates = {
                        "status": value,
                        "status_since": stamp,
                        "completed_at": stamp if value == "COMPLETED" else None,
                        "discarded_at": stamp if value == "DISCARDED" else None,
                        "completion_version": completion_version
                        if value == "COMPLETED"
                        else item["completion_version"],
                    }
                    before, after = {"status": item["status"]}, {**updates, "assigned_to": item["assigned_to"]}
                elif action in {"priority", "assigned_to"}:
                    if action == "priority" and value not in PRIORITIES:
                        raise ValueError("Prioridade inválida")
                    value = self.assignee(value) if action == "assigned_to" else value
                    updates = {action: value}
                    before, after = {action: item[action]}, updates.copy()
                elif action == "note":
                    after = {"text": required(value, "observação", 8000)}
                elif action == "technical":
                    if (
                        not isinstance(value, dict)
                        or not set(value) <= set(TECHNICAL)
                        or any(not isinstance(v, str) or len(v) > 4000 for v in value.values())
                    ):
                        raise ValueError("Informações técnicas inválidas")
                    if value.get("collected_on"):
                        try:
                            date.fromisoformat(value["collected_on"])
                        except ValueError as exc:
                            raise ValueError("Data técnica deve usar AAAA-MM-DD") from exc
                    before, after = item["technical"], {**item["technical"], **value}
                    updates = {"technical_json": encode(after)}
                elif action == "checklist":
                    if (
                        not isinstance(value, dict)
                        or not set(value) <= set(item["checklist"])
                        or any(type(v) is not bool for v in value.values())
                    ):
                        raise ValueError("Checklist inválido")
                    before = item["checklist"]
                    after = {k: {**v, "done": value.get(k, v["done"])} for k, v in before.items()}
                    updates = {"checklist_json": encode(after)}
                else:
                    raise ValueError("Ação de desenvolvimento inválida")
                if item["status"] in CLOSED and action not in {"status", "note"}:
                    raise ValueError("Reabra o item antes de alterar seus dados")
                updates.update(updated_at=stamp, revision=item["revision"] + 1)
                repo.update(item_id, updates)
                event_id = repo.event(item_id, actor, action, before, after, note, stamp)
                if action == "status" and value in {"IN_VALIDATION", "COMPLETED"}:
                    title = (
                        "Item de desenvolvimento entrou em validação"
                        if value == "IN_VALIDATION"
                        else "Item de desenvolvimento concluído"
                    )
                    self.notify(
                        repo,
                        item_id,
                        "DEV_VALIDATION" if value == "IN_VALIDATION" else "DEV_COMPLETED",
                        f"event:{event_id}",
                        "ATENCAO" if value == "IN_VALIDATION" else "INFO",
                        title,
                        note,
                        stamp,
                    )
                repo.remember(command_key, digest, item_id)
                return item_id
        except sqlite3.IntegrityError as exc:
            if "development_items.identity_key" in str(exc):
                raise ValueError("Já existe outro item ativo para esta identidade; abra o existente") from exc
            raise

    def listing(self, **kwargs):
        result = list_items(self.config.database, **kwargs)
        for item in result["items"]:
            self.age(item)
        return result

    def age(self, item):
        item["days_in_status"] = max(0, (self.clock() - datetime.fromisoformat(item["status_since"])).days)
        threshold = self.policy["stale_days"].get(item["status"])
        item["attention"] = (
            threshold is not None and item["days_in_status"] > threshold and item["status"] not in CLOSED
        )

    def detail(self, item_id, page=0):
        item = read_item(self.config.database, item_id, page)
        self.age(item)
        with DashboardRepository(self.config.database) as repo:
            item["current_base"] = repo.base_id
            target = repo.base.get(item["scanner_key"]) if item["scanner_key"] else None
            candidate = None
            if not target and repo.base_id != item["base_version"]:
                ident = item["identity"]
                expected = normalize_model(combined_model(ident["model"], ident["version"]))
                candidates = [
                    m
                    for m in repo.motos
                    if normalize_text(m.manufacturer) == ident["manufacturer"]
                    and normalize_model(m.model) == expected
                    and m.year == ident["year"]
                ]
                candidate = candidates[0] if len(candidates) == 1 else None
            item["current_scanner"] = asdict(target) if target else None
            item["reconciliation_candidate"] = asdict(candidate) if candidate else None
            original = item["source"].get("scanner") or {}
            improved = target and (
                target.status != original.get("status") or target.supported_systems != original.get("supported_systems")
            )
            item["may_be_addressed"] = bool(repo.base_id != item["base_version"] and (candidate or improved))
        item["absence_confirmed_current"] = bool(
            item["source"]["effective"].get("match_type") == "CONFIRMADO_AUSENTE_NA_BASE"
            and item["current_base"] == item["base_version"]
        )
        # A later human decision can invalidate the original absence even in the same base.
        ref = item["source"].get("reference")
        if ref and ref["kind"] != "scanner":
            try:
                current = source_snapshot(self.config.database, ref["partner"], ref["kind"], ref["id"])
                if identity_key(current)[0] == item["identity_key"]:
                    item["absence_confirmed_current"] = (
                        current["effective"].get("match_type") == "CONFIRMADO_AUSENTE_NA_BASE"
                    )
                else:
                    item["absence_confirmed_current"] = False
            except ValueError:
                item["absence_confirmed_current"] = False
        return item
