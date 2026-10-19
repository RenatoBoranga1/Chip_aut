"""Assisted operations use synthetic files, clocks and databases, never real partner credentials."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest
from test_matching import motorcycle
from test_partner_operations import confirm as direct_import
from test_partner_operations import file_bytes, rows, staged
from test_review_queue import import_base

from database.inbox_repository import read_inbox
from database.inventory_repository import read_operations
from services.motonil_staging_service import MotonilStagingService
from services.partner_health_service import partner_health, refresh_health
from services.partner_inbox_service import PartnerInboxService
from services.pipeline_lock import AlreadyRunning


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    monkeypatch.delenv("MOTO_READ_ONLY", raising=False)
    for key in ("THOMAS_API_TOKEN", "THOMAS_AUTOMATION_ENABLED", "MOTONIL_AUTOMATION_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    database = tmp_path / "inbox.sqlite3"
    import_base(database, [motorcycle()])
    paths = {}
    for partner, variable in (("thomas_motos", "THOMAS_INBOX_PATH"), ("moto_marques", "MOTO_MARQUES_INBOX_PATH")):
        paths[partner] = tmp_path / partner
        paths[partner].mkdir()
        monkeypatch.setenv(variable, str(paths[partner]))
    return database, paths, PartnerInboxService(database)


def arrive(inbox, partner="thomas_motos", data=None, kind="csv", name=None):
    database, paths, service = inbox
    target = paths[partner] / (name or "estoque." + kind)
    target.write_bytes(file_bytes(data, kind))
    service.scan(partner)
    return read_inbox(database, partner)[0]


def approve(service, row, **kwargs):
    return service.confirm(
        row["id"],
        expected_revision=row["revision"],
        preview_hash=row["preview_hash"],
        reviewer="Operador",
        confirmed=True,
        authorized=True,
        motorcycles_confirmed=True,
        accept_anomalies=True,
        **kwargs,
    )


@pytest.mark.parametrize("partner", ["thomas_motos", "moto_marques"])
@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_file_to_preview_human_confirmation_matching_review(inbox, partner, kind):
    database, _, service = inbox
    row = arrive(inbox, partner, kind=kind)
    assert row["status"] == "READY_FOR_REVIEW" and row["preview"]["valid_rows"] == 2
    assert len(row["preview"]["comparison"]["new"]) == 2
    with sqlite3.connect(database) as db:
        assert db.execute("select count(*) from partner_advertisements").fetchone()[0] == 0
    output = approve(service, row)
    assert output["imported_rows"] == 2
    assert service.get(row["id"])["status"] == "IMPORTED"
    with sqlite3.connect(database) as db:
        assert db.execute("select count(*) from review_items where partner=?", (partner,)).fetchone()[0] == 2
        assert db.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert not db.execute("pragma foreign_key_check").fetchall()


def test_scan_idempotence_hash_duplicates_and_no_repeated_previews(inbox):
    database, paths, service = inbox
    row = arrive(inbox)
    before_events = len(read_operations(database)["events"])
    result = service.scan("thomas_motos")
    assert result["thomas_motos"]["detected"] == 0
    assert service.get(row["id"])["revision"] == row["revision"]
    assert len(read_operations(database)["events"]) == before_events
    (paths["thomas_motos"] / "copia.csv").write_bytes(file_bytes())
    service.scan("thomas_motos")
    assert read_inbox(database)[0]["status"] == "DUPLICATE"
    assert len(read_inbox(database)) == 2


def test_file_already_imported_is_duplicate(inbox):
    database, _, _ = inbox
    direct_import(database)
    assert arrive(inbox)["status"] == "DUPLICATE"


def test_changed_file_is_new_version_and_old_preview_cannot_publish(inbox):
    database, paths, service = inbox
    row = arrive(inbox)
    (paths["thomas_motos"] / row["filename"]).write_bytes(file_bytes([rows()[0]]))
    with pytest.raises(ValueError, match="Arquivo mudou"):
        approve(service, row)
    service.scan("thomas_motos")
    assert len(read_inbox(database)) == 2
    assert read_inbox(database)[0]["file_hash"] != row["file_hash"]
    assert not read_operations(database)["imports"]


def test_stale_stock_and_preview_revision_are_blocked(inbox):
    database, _, service = inbox
    row = arrive(inbox)
    direct_import(database, data=[rows()[0]])
    with pytest.raises(ValueError, match="Estoque mudou"):
        approve(service, row)
    fresh = service.validate(row["id"], expected_revision=row["revision"])
    with pytest.raises(ValueError, match="desatualizada"):
        approve(service, row)
    approve(service, fresh)


def test_rejection_requires_human_and_preserves_file_and_audit(inbox):
    database, paths, service = inbox
    row = arrive(inbox)
    with pytest.raises(ValueError):
        service.reject(row["id"], expected_revision=row["revision"], reviewer="", reason="Incompleto")
    service.reject(
        row["id"], expected_revision=row["revision"], reviewer="Pessoa", reason="Exportação errada", confirmed=True
    )
    assert service.get(row["id"])["status"] == "REJECTED"
    assert (paths["thomas_motos"] / row["filename"]).is_file()
    assert not read_operations(database)["imports"]
    assert any(
        e["action"] == "FILE_REJECTED" and "Exportação errada" in e["detail_json"]
        for e in read_operations(database)["events"]
    )


@pytest.mark.parametrize(
    "content,filename",
    [
        (b"", "empty.csv"),
        (b"bad zip", "bad.xlsx"),
        (b"marca,modelo,ano\n\xff", "encoding.csv"),
        (b'brand,model\n"unfinished', "broken.csv"),
        (b"abc,xyz\none,two", "missing.csv"),
    ],
)
def test_invalid_file_does_not_break_scan(inbox, content, filename):
    database, paths, service = inbox
    (paths["thomas_motos"] / filename).write_bytes(content)
    result = service.scan("thomas_motos")
    assert result["thomas_motos"]["status"] == "SUCCESS"
    assert read_inbox(database)[0]["status"] == "INVALID"
    assert not read_operations(database)["imports"]


def test_mapping_and_incomplete_rows_need_explicit_review(inbox):
    database, paths, service = inbox
    (paths["thomas_motos"] / "mapped.csv").write_text("cod,fab,nome,ano\n1,BMW,F 900 R,2025", encoding="utf-8")
    service.scan("thomas_motos")
    row = read_inbox(database)[0]
    assert row["status"] == "INVALID"
    row = service.validate(
        row["id"],
        expected_revision=row["revision"],
        mapping={"external_id": "cod", "manufacturer": "fab", "model": "nome", "year": "ano"},
    )
    assert row["status"] == "READY_FOR_REVIEW"
    approve(service, row)
    assert read_operations(database)["mappings"]["thomas_motos"]["model"] == "nome"


@pytest.mark.parametrize("mode,active", [("INCREMENTAL", 2), ("FULL_SNAPSHOT", 1)])
def test_snapshot_and_incremental_comparison_preserve_semantics(inbox, mode, active):
    database, _, service = inbox
    data = [
        {
            **r,
            "detail_url": "https://example.com/stock/" + r["external_id"],
            "image_url": "https://example.com/images/" + r["external_id"] + ".jpg",
        }
        for r in rows()
    ]
    direct_import(database, data=data)
    row = arrive(inbox, data=[data[0]])
    row = service.validate(row["id"], expected_revision=row["revision"], mode=mode)
    diff = row["preview"]["comparison"]
    assert diff["absent"] == ["stock-2"] and diff["kept"] == ["stock-1"]
    approve(service, row)
    with sqlite3.connect(database) as db:
        assert (
            db.execute("select count(*) from partner_advertisements where not_seen_in_latest_collection=0").fetchone()[
                0
            ]
            == active
        )


def test_sharp_reduction_and_id_changes_raise_anomalies_without_import(inbox):
    database, _, service = inbox
    direct_import(database, data=[{**rows()[0], "external_id": str(i)} for i in range(100)])
    row = arrive(inbox, data=[{**rows()[0], "external_id": "new-" + str(i)} for i in range(4)])
    messages = str(row["preview"]["anomalies"])
    assert "Forte redução" in messages and "mudança de IDs" in messages
    with pytest.raises(ValueError, match="anomalias"):
        service.confirm(
            row["id"],
            expected_revision=row["revision"],
            preview_hash=row["preview_hash"],
            reviewer="Pessoa",
            confirmed=True,
            authorized=True,
            motorcycles_confirmed=True,
        )
    assert len(read_operations(database)["imports"]) == 1


def test_confirmation_rollback_keeps_inbox_ready(inbox, monkeypatch):
    import services.partner_inventory_import as importer

    database, _, service = inbox
    row = arrive(inbox)
    monkeypatch.setattr(importer, "build_coverage", lambda *a, **kw: (_ for _ in ()).throw(ValueError("failure")))
    with pytest.raises(ValueError):
        approve(service, row)
    assert service.get(row["id"])["status"] == "READY_FOR_REVIEW"
    assert not read_operations(database)["imports"]


def test_lock_path_guard_read_only_and_recover_intermediate(inbox, monkeypatch):
    database, _, service = inbox
    with pytest.raises(ValueError, match="Nome"):
        service.file_content("thomas_motos", "../outside.csv")
    with service.lock("thomas_motos"), pytest.raises(AlreadyRunning):
        service.scan("thomas_motos")
    row = arrive(inbox)
    with sqlite3.connect(database) as db:
        db.execute("update partner_inbox set status='VALIDATING' where id=?", (row["id"],))
    service.scan("thomas_motos")
    assert service.get(row["id"])["status"] == "READY_FOR_REVIEW"
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    with pytest.raises(ValueError, match="somente leitura"):
        service.scan()


def selections(database, identifiers, identity=None):
    by_id = {r["external_id"]: r for r in read_operations(database)["staging"]}
    return [
        {
            "partner": "motonil",
            "external_id": str(i),
            "revision": by_id[str(i)]["revision"],
            "identity": identity or rows()[0],
        }
        for i in identifiers
    ]


def test_motonil_ten_items_six_memories_four_human_decisions(inbox):
    database, _, _ = inbox
    service = MotonilStagingService(database)
    items = [staged(str(i), "Item " + str(i)) for i in range(10)]
    service.stage(items[:6])
    service.classify_batch(selections(database, [0, 1]), "MOTORCYCLE", reviewer="Pessoa", confirmed=True)
    service.classify_batch(selections(database, [2, 3]), "KART", reviewer="Pessoa", confirmed=True)
    service.classify_batch(selections(database, [4, 5]), "SERVICE", reviewer="Pessoa", confirmed=True)
    result = service.stage(items)
    assert result["reused_decisions"] == 6
    assert read_operations(database)["metrics"]["pending_triage"] == 4
    service.classify_batch(selections(database, [6, 7]), "MOTORCYCLE", reviewer="Pessoa", confirmed=True)
    service.classify_batch(selections(database, [8]), "KART", reviewer="Pessoa", confirmed=True)
    service.classify_batch(selections(database, [9]), "SERVICE", reviewer="Pessoa", confirmed=True)
    with sqlite3.connect(database) as db:
        assert db.execute("select count(*) from partner_advertisements where partner='motonil'").fetchone()[0] == 4
    assert read_operations(database)["metrics"]["pending_triage"] == 0
    assert partner_health(database)["efficiency"]["reused"] == 6


@pytest.mark.parametrize("problem", ["stale", "mixed", "identity", "confirmation"])
def test_motonil_batch_is_atomic_and_requires_current_human_confirmation(inbox, problem):
    database, _, _ = inbox
    service = MotonilStagingService(database)
    service.stage([staged("1"), staged("2")])
    batch = selections(database, [1, 2])
    if problem == "stale":
        batch[1]["revision"] = 0
    if problem == "mixed":
        batch[1]["partner"] = "wr_motos"
    if problem == "identity":
        batch[1]["identity"] = {}
    with pytest.raises(ValueError):
        service.classify_batch(batch, "MOTORCYCLE", reviewer="Pessoa", confirmed=problem != "confirmation")
    assert read_operations(database)["metrics"]["pending_triage"] == 2
    with sqlite3.connect(database) as db:
        assert db.execute("select count(*) from partner_advertisements").fetchone()[0] == 0


def test_motonil_fallback_identity_and_change_invalidation(inbox):
    database, _, _ = inbox
    service = MotonilStagingService(database)
    item = staged()
    item.pop("external_id")
    service.stage([item])
    row = read_operations(database)["staging"][0]
    service.classify_batch(selections(database, [row["external_id"]]), "KART", reviewer="Pessoa", confirmed=True)
    assert service.stage([item])["reused_decisions"] == 1
    service.stage([{**item, "title": "Identidade mudou"}])
    assert read_operations(database)["staging"][0]["classification"] == "PENDING_CLASSIFICATION"


def test_staleness_alert_deduplication_and_resolution(inbox):
    database, _, service = inbox
    row = arrive(inbox)
    approve(service, row)

    def future():
        return datetime.now(timezone.utc) + timedelta(days=30)

    first = refresh_health(database, clock=future)
    assert next(p for p in first["partners"] if p["partner"] == "thomas_motos")["health"] == "Desatualizado"
    before = read_operations(database)["alerts"]
    refresh_health(database, clock=future)
    assert read_operations(database)["alerts"] == before
    refresh_health(database)
    assert not any(a["code"] == "PARTNER_IMPORT_STALE" for a in read_operations(database)["alerts"])


def test_scheduler_poll_intervals_and_run_all_never_publish(inbox, monkeypatch):
    from services.multi_partner_service import run_all
    from services.partner_operation_scheduler import run_operation
    from services.scheduler_config import load_config

    database, paths, service = inbox
    (paths["thomas_motos"] / "stock.csv").write_bytes(file_bytes())
    result = run_operation(database, load_config(), partner_key="thomas_motos")
    assert result["status"] == "SUCCESS"
    assert service.scan("thomas_motos", force=False)["thomas_motos"]["status"] == "NOT_DUE"
    # Default registry is replaced only at construction; no public HTTP calls.
    monkeypatch.setattr("services.multi_partner_service.PartnerRegistry", lambda: SimpleNamespace(list=lambda **kw: []))
    assert run_all(database, load_config())["partner_inbox"]["status"] == "SUCCESS"
    assert not read_operations(database)["imports"]


def test_cli_and_ai_are_read_only_and_expose_pending_file(inbox, capsys):
    from app.partners import main
    from services.ai_assistant_service import AIAssistantService
    from services.ai_context_service import new_conversation
    from services.ai_provider import AssistantConfig

    database, _, _ = inbox
    arrive(inbox)
    before = database.read_bytes()
    assert main(["inbox", "list", "--db", str(database)]) == 0
    assert "READY_FOR_REVIEW" in capsys.readouterr().out
    assistant = AIAssistantService(database, config=AssistantConfig(enabled=True, provider="fake", audit_enabled=False))
    answer = assistant.ask("Há arquivos aguardando confirmação?", new_conversation())
    assert answer["success"] and answer["route"] == "Parceiros"
    assert any("arquivos aguardando confirmação: 1" in f["text"] for f in answer["facts"])
    for question in ["Confirme arquivo", "Rejeite arquivo", "Classifique Motonil", "Importe o arquivo"]:
        assert assistant.ask(question, new_conversation())["intent"] == "BLOCKED"
    assert database.read_bytes() == before


def test_dashboard_inbox_health_and_batch_render_read_only(inbox, monkeypatch):
    database, _, _ = inbox
    arrive(inbox)
    monkeypatch.setenv("MOTO_DB", str(database))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    app = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Parceiros").run()
    assert not app.exception
    assert any(x.value == "Arquivos aguardando análise" for x in app.subheader)
    assert any(x.value == "Saúde dos parceiros" for x in app.subheader)
    assert any(x.label == "Confirmar importação da inbox" and x.disabled for x in app.button)


def test_dashboard_review_form_publishes_only_after_explicit_submission(inbox, monkeypatch):
    database, _, _ = inbox
    row = arrive(inbox)
    monkeypatch.setenv("MOTO_DB", str(database))
    monkeypatch.setenv("MOTO_READ_ONLY", "0")
    app = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Parceiros").run()
    next(t for t in app.text_input if t.label == "Responsável pela revisão do arquivo").set_value("Pessoa teste")
    for label in [
        "Confirmo origem autorizada e unidade correta",
        "Conferi as motocicletas e o modo de importação",
        "Conferi as anomalias e os possíveis ausentes",
    ]:
        next(c for c in app.checkbox if c.label == label).check()
    assert not read_operations(database)["imports"]
    next(b for b in app.button if b.label == "Confirmar importação da inbox").click().run()
    assert not app.exception
    assert PartnerInboxService(database).get(row["id"])["status"] == "IMPORTED"


@pytest.mark.parametrize("flag", ["confirmed", "authorized", "motorcycles_confirmed"])
def test_inbox_cannot_bypass_import_confirmation(inbox, flag):
    database, _, service = inbox
    row = arrive(inbox)
    flags = dict(confirmed=True, authorized=True, motorcycles_confirmed=True)
    flags[flag] = False
    with pytest.raises(ValueError, match="Confirme"):
        service.confirm(
            row["id"],
            expected_revision=row["revision"],
            preview_hash=row["preview_hash"],
            reviewer="Pessoa",
            accept_anomalies=True,
            **flags,
        )
    assert not read_operations(database)["imports"]
    assert service.get(row["id"])["status"] == "READY_FOR_REVIEW"


def test_known_terminal_files_use_stat_cache_without_reading_again(inbox, monkeypatch):
    _, _, service = inbox
    arrive(inbox)
    monkeypatch.setattr(service, "file_content", lambda *a: pytest.fail("Releitura de arquivo conhecido"))
    assert service.scan("thomas_motos")["thomas_motos"]["skipped"] == 1


def test_oversized_file_has_cached_error_and_recovers_when_replaced(inbox):
    database, paths, service = inbox
    target = paths["thomas_motos"] / "oversized.csv"
    with target.open("wb") as handle:
        handle.truncate(10_000_001)
    service.scan("thomas_motos")
    assert partner_health(database)["invalid"] == 1
    events = len(read_operations(database)["events"])
    service.scan("thomas_motos")
    assert len(read_operations(database)["events"]) == events
    target.write_bytes(file_bytes())
    service.scan("thomas_motos")
    assert partner_health(database)["invalid"] == 0
    assert read_inbox(database)[0]["status"] == "READY_FOR_REVIEW"


def test_configurable_scheduler_tick_prepares_only(inbox, tmp_path):
    from dataclasses import asdict

    from services.partner_operation_scheduler import serve_operation
    from services.scheduler_config import SchedulerConfig

    database, paths, _ = inbox
    (paths["moto_marques"] / "stock.csv").write_bytes(file_bytes())
    path = tmp_path / "scheduler.json"
    path.write_text(json.dumps(asdict(SchedulerConfig())), encoding="utf-8")
    serve_operation(database, path, partner_key="moto_marques", max_ticks=1)
    assert read_inbox(database, "moto_marques")[0]["status"] == "READY_FOR_REVIEW"
    assert not read_operations(database)["imports"]


def test_full_snapshot_invalid_blocks_and_motonil_stale_is_deduplicated(inbox):
    database, _, service = inbox
    row = arrive(inbox, data=[rows()[0], {**rows()[1], "year": ""}])
    assert row["status"] == "READY_FOR_REVIEW"
    row = service.validate(row["id"], expected_revision=row["revision"], mode="FULL_SNAPSHOT")
    assert row["status"] == "INVALID"
    with pytest.raises(ValueError):
        approve(service, row)
    MotonilStagingService(database).stage([staged()])

    def future():
        return datetime.now(timezone.utc) + timedelta(days=10)

    refresh_health(database, clock=future)
    refresh_health(database, clock=future)
    alerts = [a for a in read_operations(database)["alerts"] if a["code"] == "PARTNER_TRIAGE_STALE"]
    assert len(alerts) == 1 and alerts[0]["occurrences"] == 1
