"""Bounded polling prepares reviews. Only explicit, current human confirmation publishes."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from database.inbox_repository import read_inbox
from database.inventory_repository import event, read_operations
from database.partner_repository import PartnerRepository
from database.repository import encode
from database.transaction import atomic_database
from services.partner_inventory_import import (
    FIELDS,
    PartnerInventoryImportService,
    default_mapping,
    read_file,
    writable,
)
from services.partner_operations_config import INBOX_ENV, inbox_root, load_policy
from services.pipeline_lock import ExecutionLock


def digest(content):
    return hashlib.sha256(content).hexdigest()


def stat_stamp(path):
    s = path.stat()
    return encode([s.st_size, s.st_mtime_ns, s.st_ctime_ns])


def stock_state(db, partner):
    marker = db.execute("SELECT MAX(id) FROM partner_collections WHERE partner=?", (partner,)).fetchone()[0]
    data = {}
    for identifier, payload in db.execute(
        "SELECT external_id,payload_json FROM partner_advertisements WHERE partner=? AND not_seen_in_latest_collection=0",
        (partner,),
    ):
        row = json.loads(payload)
        row["detail_url"] = row.get("source_url")
        row["image_url"] = row.get("primary_image_url")
        data[identifier] = {k: row.get(k) or None for k in FIELDS if k != "external_id"}
    return marker, data


def comparison(preview, previous, policy):
    current = {
        r["data"]["external_id"]: {k: r["data"].get(k) or None for k in FIELDS if k != "external_id"}
        for r in preview["rows"]
        if not r["errors"]
    }
    old, new = set(previous), set(current)
    changes = [key for key in sorted(old & new) if current[key] != previous[key]]
    result = {
        "new": sorted(new - old),
        "changed": changes,
        "kept": sorted((old & new) - set(changes)),
        "absent": sorted(old - new),
        "invalid": preview["invalid_rows"],
    }
    warnings = []
    if not new or (preview["mode"] == "FULL_SNAPSHOT" and preview["invalid_rows"]):
        warnings.append(
            {"level": "BLOQUEIO", "message": "Sem linhas válidas ou retrato completo com linhas inválidas."}
        )
    if old and len(new) < len(old) * policy["reduction_ratio"]:
        warnings.append({"level": "ATENÇÃO", "message": "Forte redução na quantidade de anúncios."})
    if old and new and len(new - old) / len(new) >= policy["id_change_ratio"]:
        warnings.append({"level": "ATENÇÃO", "message": "Grande mudança de IDs; confira estrutura e unidade."})
    if preview["invalid_rows"] / max(1, preview["total_rows"]) >= policy["invalid_ratio"]:
        warnings.append({"level": "ATENÇÃO", "message": "Qualidade baixa: muitas linhas inválidas."})
    if preview["missing_id"]:
        warnings.append(
            {"level": "ATENÇÃO", "message": "Há linhas sem código de estoque; confira a estabilidade dos IDs."}
        )
    if preview["mode"] == "INCREMENTAL" and result["absent"]:
        warnings.append({"level": "INFO", "message": "Ausentes serão preservados no modo incremental."})
    return result, warnings


class PartnerInboxService:
    def __init__(self, database, *, read_only=False, reports=None, clock=None):
        self.database = Path(database)
        self.read_only = read_only
        self.reports = reports
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def stamp(self):
        return self.clock().isoformat()

    def lock(self, partner):
        if partner not in INBOX_ENV:
            raise ValueError("Parceiro sem inbox")
        return ExecutionLock(self.database, "inbox_" + partner)

    def file_content(self, partner, filename):
        root = inbox_root(partner)
        if root is None or not root.is_dir():
            raise ValueError("Pasta de entrada não configurada ou indisponível")
        if Path(filename).name != filename or any(c in filename for c in ("/", "\\", ":")) or filename in {".", ".."}:
            raise ValueError("Nome de arquivo inválido")
        path = root / filename
        if path.is_symlink() or path.resolve().parent != root or not path.is_file():
            raise ValueError("Arquivo fora da pasta de entrada ou indisponível")
        if path.suffix.lower() not in {".csv", ".xlsx"}:
            raise ValueError("Formato permitido: CSV ou XLSX")
        before = stat_stamp(path)
        if path.stat().st_size > 10_000_000:
            raise ValueError("Arquivo maior que 10 MB")
        with path.open("rb") as handle:
            content = handle.read(10_000_001)
        if len(content) > 10_000_000 or before != stat_stamp(path) or path.is_symlink():
            raise ValueError("Arquivo mudou durante a leitura; aguarde terminar a gravação")
        return content, before

    def scan(self, partner=None, *, force=True):
        writable(self.database, self.read_only)
        results = {}
        for key in [partner] if partner else INBOX_ENV:
            with self.lock(key):
                root = inbox_root(key)
                if root is None:
                    results[key] = {"status": "NOT_CONFIGURED", "detected": 0}
                    continue
                if not root.is_dir():
                    results[key] = {"status": "UNAVAILABLE", "detected": 0}
                    continue
                with PartnerRepository(self.database) as repo:
                    saved = repo.connection.execute(
                        "SELECT last_scan_at FROM partner_inbox_scans WHERE partner=?", (key,)
                    ).fetchone()
                interval = load_policy()[key]["scan_interval_minutes"] * 60
                if not force and saved and (self.clock() - datetime.fromisoformat(saved[0])).total_seconds() < interval:
                    results[key] = {"status": "NOT_DUE", "detected": 0}
                    continue
                detected = skipped = errors = 0
                # Flat directory only. Bound new work; existing terminal entries use stat cache.
                processed = 0
                for path in root.iterdir():
                    if (
                        path.suffix.lower() not in {".csv", ".xlsx"}
                        or path.name.startswith("~$")
                        or path.is_symlink()
                        or not path.is_file()
                    ):
                        continue
                    stamp = ""
                    try:
                        stamp = stat_stamp(path)
                        with PartnerRepository(self.database) as repo:
                            read_error = repo.connection.execute(
                                "SELECT stat_json FROM partner_inbox_errors WHERE partner=? AND filename=? AND active=1",
                                (key, path.name),
                            ).fetchone()
                            prior = repo.connection.execute(
                                "SELECT id,stat_json,status FROM partner_inbox WHERE partner=? AND filename=? ORDER BY id DESC LIMIT 1",
                                (key, path.name),
                            ).fetchone()
                        if read_error and read_error[0] == stamp:
                            skipped += 1
                            continue
                        if prior and prior[1] == stamp:
                            if prior[2] in {"DETECTED", "VALIDATING"}:
                                self._validate(prior[0])
                            else:
                                skipped += 1
                            continue
                        if processed >= 100:
                            break
                        processed += 1
                        content, stamp = self.file_content(key, path.name)
                        hashed = digest(content)
                        with PartnerRepository(self.database) as repo, repo.connection:
                            db = repo.connection
                            db.execute(
                                "UPDATE partner_inbox_errors SET active=0 WHERE partner=? AND filename=?",
                                (key, path.name),
                            )
                            same = db.execute(
                                "SELECT id FROM partner_inbox WHERE partner=? AND filename=? AND file_hash=?",
                                (key, path.name, hashed),
                            ).fetchone()
                            if same:
                                db.execute("UPDATE partner_inbox SET stat_json=? WHERE id=?", (stamp, same[0]))
                                skipped += 1
                                continue
                            duplicate = (
                                db.execute(
                                    "SELECT 1 FROM partner_inbox WHERE partner=? AND file_hash=?", (key, hashed)
                                ).fetchone()
                                or db.execute(
                                    "SELECT 1 FROM partner_inventory_imports WHERE partner=? AND file_hash=?",
                                    (key, hashed),
                                ).fetchone()
                            )
                            cur = db.execute(
                                "INSERT INTO partner_inbox(partner,filename,file_hash,detected_at,updated_at,status,stat_json) VALUES (?,?,?,?,?,?,?)",
                                (
                                    key,
                                    path.name,
                                    hashed,
                                    self.stamp(),
                                    self.stamp(),
                                    "DUPLICATE" if duplicate else "DETECTED",
                                    stamp,
                                ),
                            )
                            identifier = cur.lastrowid
                            event(
                                db,
                                key,
                                "FILE_DETECTED",
                                "sistema",
                                {"inbox_id": identifier, "filename": path.name, "file_hash": hashed},
                            )
                        detected += 1
                        if not duplicate:
                            self._validate(identifier)
                    except (OSError, ValueError):
                        # No fabricated content hash for oversized/unreadable files.
                        # Metadata cache retries only after a change; the original file stays untouched.
                        errors += 1
                        with PartnerRepository(self.database) as repo, repo.connection:
                            repo.connection.execute(
                                "INSERT INTO partner_inbox_errors VALUES (?,?,?,?,?,1) ON CONFLICT(partner,filename) DO UPDATE SET stat_json=excluded.stat_json,error=excluded.error,updated_at=excluded.updated_at,active=1",
                                (
                                    key,
                                    path.name,
                                    stamp,
                                    "Arquivo indisponível, instável ou maior que 10 MB",
                                    self.stamp(),
                                ),
                            )
                            event(
                                repo.connection,
                                key,
                                "FILE_READ_FAILED",
                                "sistema",
                                {"filename": path.name, "status": "INVALID"},
                            )
                summary = {"status": "SUCCESS", "detected": detected, "skipped": skipped, "unreadable": errors}
                with PartnerRepository(self.database) as repo, repo.connection:
                    repo.connection.execute(
                        "INSERT INTO partner_inbox_scans VALUES (?,?,?) ON CONFLICT(partner) DO UPDATE SET last_scan_at=excluded.last_scan_at,result_json=excluded.result_json",
                        (key, self.stamp(), encode(summary)),
                    )
                results[key] = summary
        from services.partner_health_service import refresh_health

        refresh_health(self.database, clock=self.clock)
        return results

    def get(self, identifier):
        rows = read_inbox(self.database, identifier=identifier)
        if not rows:
            raise ValueError("Arquivo da inbox não encontrado")
        return rows[0]

    def validate(self, identifier, *, mapping=None, mode="INCREMENTAL", expected_revision=None):
        writable(self.database, self.read_only)
        if mode not in {"INCREMENTAL", "FULL_SNAPSHOT"}:
            raise ValueError("Modo de importação inválido")
        row = self.get(identifier)
        with self.lock(row["partner"]):
            return self._validate(identifier, mapping=mapping, mode=mode, expected_revision=expected_revision)

    def _validate(self, identifier, *, mapping=None, mode=None, expected_revision=None):
        row = self.get(identifier)
        if expected_revision is not None and row["revision"] != expected_revision:
            raise ValueError("Revisão desatualizada; abra o arquivo novamente")
        if row["status"] in {"IMPORTED", "REJECTED", "DUPLICATE"}:
            raise ValueError("Arquivo já finalizado")
        with PartnerRepository(self.database) as repo, repo.connection:
            repo.connection.execute(
                "UPDATE partner_inbox SET status='VALIDATING',updated_at=? WHERE id=?", (self.stamp(), identifier)
            )
        try:
            content, _ = self.file_content(row["partner"], row["filename"])
            if digest(content) != row["file_hash"]:
                raise ValueError("Arquivo mudou; execute nova leitura da inbox")
            headers, _ = read_file(content, row["filename"])
            saved = read_operations(self.database)["mappings"].get(row["partner"], {})
            mapping = (
                mapping
                if mapping is not None
                else {**default_mapping(headers), **{k: v for k, v in saved.items() if v in headers}}
            )
            mode = mode or row["mode"]
            preview = PartnerInventoryImportService(self.database).preview(
                row["partner"], content, row["filename"], mapping=mapping, mode=mode
            )
            with PartnerRepository(self.database) as repo:
                marker, old = stock_state(repo.connection, row["partner"])
            diff, warnings = comparison(preview, old, load_policy()["anomalies"])
            preview.update(comparison=diff, anomalies=warnings, stock_marker=marker)
            blocked = any(w["level"] == "BLOQUEIO" for w in warnings)
            status, error = ("INVALID" if blocked else "READY_FOR_REVIEW"), None
        except (ValueError, OSError, TypeError):
            preview, mapping, status, error = (
                {},
                mapping or {},
                "INVALID",
                "Arquivo inválido, alterado ou incompleto; confira formato, campos e pasta de entrada.",
            )
            mode = mode or row["mode"]
        token = digest(encode(preview).encode()) if preview else None
        with PartnerRepository(self.database) as repo, repo.connection:
            repo.connection.execute(
                "UPDATE partner_inbox SET status=?,revision=revision+1,updated_at=?,mode=?,mapping_json=?,preview_json=?,preview_hash=?,error=? WHERE id=?",
                (status, self.stamp(), mode, encode(mapping), encode(preview), token, error, identifier),
            )
            event(
                repo.connection, row["partner"], "FILE_VALIDATED", "sistema", {"inbox_id": identifier, "status": status}
            )
        return self.get(identifier)

    def confirm(
        self,
        identifier,
        *,
        expected_revision,
        preview_hash,
        reviewer,
        confirmed=False,
        authorized=False,
        motorcycles_confirmed=False,
        accept_anomalies=False,
    ):
        writable(self.database, self.read_only)
        row = self.get(identifier)
        with (
            self.lock(row["partner"]),
            ExecutionLock(self.database, partner=row["partner"]),
            atomic_database(self.database),
            PartnerRepository(self.database) as repo,
        ):
            # Read on the transaction connection: no stale secondary connection while holding a writer.
            current = repo.connection.execute(
                "SELECT revision,status,preview_hash FROM partner_inbox WHERE id=?", (identifier,)
            ).fetchone()
            if current != (expected_revision, "READY_FOR_REVIEW", preview_hash) or row["revision"] != expected_revision:
                raise ValueError("Prévia desatualizada ou arquivo não está pronto; revise novamente")
            content, _ = self.file_content(row["partner"], row["filename"])
            if digest(content) != row["file_hash"]:
                raise ValueError("Arquivo mudou; bloqueada a confirmação da prévia antiga")
            marker, _ = stock_state(repo.connection, row["partner"])
            if marker != row["preview"]["stock_marker"]:
                raise ValueError("Estoque mudou após a prévia; valide novamente")
            if any(w["level"] == "ATENÇÃO" for w in row["preview"]["anomalies"]) and not accept_anomalies:
                raise ValueError("Confirme a conferência das anomalias")
            result = PartnerInventoryImportService(self.database, reports=self.reports).confirm(
                row["partner"],
                content,
                row["filename"],
                reviewer=reviewer,
                confirmed=confirmed,
                authorized=authorized,
                motorcycles_confirmed=motorcycles_confirmed,
                mapping=row["mapping"],
                mode=row["mode"],
            )
            repo.connection.execute(
                "UPDATE partner_inbox SET status='IMPORTED',import_id=?,revision=revision+1,updated_at=? WHERE id=?",
                (result["id"], self.stamp(), identifier),
            )
            event(
                repo.connection,
                row["partner"],
                "FILE_CONFIRMED",
                reviewer,
                {"inbox_id": identifier, "import_id": result["id"]},
            )
        from services.partner_health_service import refresh_health
        from services.prioritization_service import safe_refresh

        safe_refresh(self.database, row["partner"], "collection")
        refresh_health(self.database, clock=self.clock)
        return result

    def reject(self, identifier, *, expected_revision, reviewer, reason, confirmed=False):
        writable(self.database, self.read_only)
        row = self.get(identifier)
        if not confirmed or not reviewer.strip() or not reason.strip():
            raise ValueError("Confirme a rejeição e informe responsável e motivo")
        with self.lock(row["partner"]), PartnerRepository(self.database) as repo, repo.connection:
            cur = repo.connection.execute(
                "UPDATE partner_inbox SET status='REJECTED',revision=revision+1,updated_at=? WHERE id=? AND revision=? AND status IN ('DETECTED','VALIDATING','READY_FOR_REVIEW','INVALID')",
                (self.stamp(), identifier, expected_revision),
            )
            if cur.rowcount != 1:
                raise ValueError("Arquivo mudou ou já foi finalizado")
            event(
                repo.connection,
                row["partner"],
                "FILE_REJECTED",
                reviewer,
                {"inbox_id": identifier, "reason": reason.strip()[:2000]},
            )
        from services.partner_health_service import refresh_health

        refresh_health(self.database, clock=self.clock)
        return self.get(identifier)


def poll_inboxes(database, *, clock=None):
    """Scheduler-safe boundary: an inbox failure never prevents other partner runs."""
    try:
        return PartnerInboxService(database, clock=clock).scan(force=False)
    except Exception:
        return {"status": "FAILED", "message": "Leitura da inbox não concluída; tente novamente."}
