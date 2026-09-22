import json
import sqlite3
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from test_matching import motorcycle

from database.partner_repository import PartnerRepository
from database.review_repository import ReviewRepository
from matching.review_policy import load_policy, priority, signature
from partners.models import CollectionResult, PartnerMotorcycle
from scanner_base.models import ParsedBase
from services.coverage_service import build_coverage
from services.review_service import collection_changes


def ad(**kwargs):
    values = dict(
        partner="wr_motos",
        external_id="1",
        manufacturer="BMW",
        model="F 900 R",
        version=None,
        year=2025,
        raw_name="BMW F 900 R",
        source_url="https://example.test/1",
        collected_at="2026-09-22T12:00:00+00:00",
        raw_text="original",
        normalized_key=None,
    )
    return PartnerMotorcycle(**(values | kwargs))


def import_base(path, motos):
    with PartnerRepository(path) as repo:
        return repo.save_import(ParsedBase(motorcycles=motos), "fixture", "hash", {"manufacturer_aliases": {}}, {})[0]


def collect(path, ads, complete=True):
    with PartnerRepository(path) as repo:
        return repo.save_collection(
            CollectionResult(
                partner="wr_motos",
                collected_at=ads[0].collected_at if ads else "now",
                advertisements=ads,
                complete=complete,
            )
        )


def coverage(path, ads, folder):
    cid = collect(path, ads)
    return build_coverage(cid, path, folder)


@pytest.fixture
def queue(tmp_path):
    path = tmp_path / "db.sqlite3"
    import_base(path, [motorcycle(), motorcycle("F 900 R GT")])
    report = coverage(path, [ad()], tmp_path / "reports")
    item_id = report["groups"]["REVISAR"][0]["review_item_id"]
    return path, item_id


def decide(repo, item_id, action="CONFIRMAR_MATCH", candidate="BMW|F900R|2025"):
    return repo.decide(item_id, action, "Fixture reviewer", "Fixture justification", candidate)


def test_queue_creation_keeps_complete_source(queue):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        item = repo.show(item_id)
        assert item["state"] == "pending" and item["priority"] == "medium"
        assert item["advertisement"] == asdict(ad())
        assert item["automatic"]["match_type"] == "AMBIGUOUS"
        assert item["automatic"]["candidates"] and item["occurrences"] == 1
        assert item["human_decision"] is None


def test_confirm_preserves_automatic_and_base_status(queue, tmp_path):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        before = repo.show(item_id)
        confirmed = decide(repo, item_id)
        assert confirmed["automatic"] == before["automatic"]
        assert confirmed["effective"]["scanner_key"] == "BMW|F900R|2025"
        assert confirmed["effective"]["scanner_status"] == motorcycle().status
        assert confirmed["effective"]["confidence"] is None
        assert confirmed["state"] == "resolved"
    report = coverage(path, [ad()], tmp_path / "after")
    entry = report["groups"][motorcycle().status][0]
    assert entry["automatic_result"]["match_type"] == "AMBIGUOUS"
    assert entry["effective_result"]["match_type"] == "EXATO_CONFIRMADO_HUMANAMENTE"
    assert report["review_queue"]["reused"] == 1
    with ReviewRepository(path) as repo:
        assert len(repo.list_items()) == 1
        assert repo.show(item_id)["occurrences"] == 2


def test_same_collection_rerun_is_idempotent(queue, tmp_path):
    path, item_id = queue
    build_coverage(1, path, tmp_path / "again")
    with ReviewRepository(path) as repo:
        assert len(repo.list_items()) == 1
        assert repo.show(item_id)["occurrences"] == 1


def test_reject_keeps_pending_and_never_promotes_other_candidate(queue):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        item = decide(repo, item_id, "REJEITAR_CANDIDATO")
        assert item["state"] == "pending"
        assert item["effective"]["scanner_key"] is None
        assert "BMW|F900R|2025" not in {c["scanner_key"] for c in item["effective"]["candidates"]}
        assert "BMW|F900R|2025" in {c["scanner_key"] for c in item["automatic"]["candidates"]}


def test_no_match_is_not_no_support(queue, tmp_path):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        item = decide(repo, item_id, "NAO_EXISTE_NA_BASE", None)
        assert item["effective"]["match_type"] == "CONFIRMADO_AUSENTE_NA_BASE"
        assert item["effective"]["scanner_status"] is None
    report = coverage(path, [ad(external_id="2")], tmp_path / "after")
    assert report["counts"]["CONFIRMADO_AUSENTE_NA_BASE"] == 1
    assert report["counts"]["SEM_SUPORTE"] == 0


@pytest.mark.parametrize("action,state", [("DEIXAR_PENDENTE", "deferred"), ("IGNORAR", "ignored")])
def test_local_actions_do_not_leak_to_other_ads(queue, tmp_path, action, state):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        assert decide(repo, item_id, action, None)["state"] == state
    coverage(path, [ad(external_id="2")], tmp_path / "after")
    with ReviewRepository(path) as repo:
        assert repo.list_items()[-1]["state"] == "pending"


def test_latest_decision_and_audit_chain(queue):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        first = decide(repo, item_id)
        second = decide(repo, item_id, "NAO_EXISTE_NA_BASE", None)
        third = decide(repo, item_id, "DEIXAR_PENDENTE", None)
        assert third["state"] == "deferred" and third["effective"] == third["automatic"]
        assert len(third["history"]) == 3
        assert second["human_decision"]["previous_decision_id"] == first["human_decision"]["id"]
        assert third["human_decision"]["previous_decision_id"] == second["human_decision"]["id"]
        for event in third["history"]:
            assert event["reviewer"] and event["created_at"] and event["identity_json"] and event["policy_json"]


@pytest.mark.parametrize("reviewer,note", [("", "note"), ("  ", "note"), ("Renato", ""), ("Renato", "  ")])
def test_required_audit_fields_rollback(queue, reviewer, note):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        with pytest.raises(ValueError):
            repo.decide(item_id, "NAO_EXISTE_NA_BASE", reviewer, note)
        assert repo.show(item_id)["history"] == []


@pytest.mark.parametrize("candidate", ["BMW|F900R|2024", "MISSING", ""])
def test_invalid_candidate_does_not_persist(queue, candidate):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        with pytest.raises(ValueError):
            decide(repo, item_id, candidate=candidate)
        assert repo.show(item_id)["history"] == []


@pytest.mark.parametrize("action", ["NAO_EXISTE_NA_BASE", "REJEITAR_CANDIDATO"])
def test_negative_memory_stale_on_any_new_base(queue, action):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        decide(repo, item_id, action, "BMW|F900R|2025" if action == "REJEITAR_CANDIDATO" else None)
    import_base(path, [motorcycle()])
    with ReviewRepository(path) as repo:
        item = repo.show(item_id)
        assert item["state"] == "invalidated" and not item["memory"]["valid"]
        assert item["effective"]["scanner_key"] is None
        assert len(item["events"]) == 1
        assert len(repo.show(item_id)["events"]) == 1
        assert len(item["history"]) == 1


def test_positive_survives_base_update_and_reads_current_support(queue):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        decide(repo, item_id)
    import_base(path, [motorcycle(status="SEM_SUPORTE")])
    with ReviewRepository(path) as repo:
        item = repo.show(item_id)
        assert item["memory"]["valid"]
        assert item["effective"]["scanner_status"] == "SEM_SUPORTE"
        assert item["automatic"]["candidates"][0]["scanner_status"] != "SEM_SUPORTE"


@pytest.mark.parametrize("changed", ["removed", "identity"])
def test_positive_invalidated_when_target_removed_or_changed(queue, changed):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        decide(repo, item_id)
    moto = motorcycle()
    if changed == "identity":
        moto = replace(moto, model="F 900 R SPECIAL")
    import_base(path, [moto] if changed == "identity" else [])
    with ReviewRepository(path) as repo:
        assert repo.show(item_id)["state"] == "invalidated"


@pytest.mark.parametrize(
    "changes",
    [
        {"year": 2024},
        {"version": "GT"},
        {"model": "F 900 RR"},
        {"model": "F 900 R ABS"},
        {"model": "F 900 R TOURING"},
        {"model": "F 900 R LIMITED"},
        {"model": "F 700 R"},
        {"manufacturer": "HONDA"},
        {"partner": "other_partner"},
        {"model": "F 900 R *PROMOÇÃO*"},
    ],
)
def test_memory_never_crosses_identity_boundaries(queue, tmp_path, changes):
    path, item_id = queue
    import_base(path, [motorcycle()])
    build_coverage(1, path, tmp_path / "explicit")
    with ReviewRepository(path) as repo:
        decide(repo, item_id)
    report = coverage(path, [ad(external_id="2", **changes)], tmp_path / "different")
    assert report["review_queue"]["reused"] == 0
    for group in report["groups"].values():
        for item in group:
            assert item["human_decision"] is None


@pytest.mark.parametrize(
    "left,right",
    [
        ("R 1250 GS", "R 1250 GS ADVENTURE"),
        ("R", "RR"),
        ("STANDARD", "TOURING"),
        ("LIMITED", "SPECIAL"),
        ("114", "117"),
        ("650", "700"),
        ("ABS", ""),
    ],
)
def test_strict_signature_protects_critical_tokens(left, right):
    assert signature(asdict(ad(model=left))) != signature(asdict(ad(model=right)))


def test_valid_memory_between_external_ids_with_cosmetic_spacing(queue, tmp_path):
    path, item_id = queue
    import_base(path, [motorcycle()])
    build_coverage(1, path, tmp_path / "explicit")
    with ReviewRepository(path) as repo:
        decide(repo, item_id)
    report = coverage(path, [ad(external_id="2", model="F-900-R")], tmp_path / "other")
    assert report["review_queue"]["reused"] == 1
    with ReviewRepository(path) as repo:
        second = repo.list_items()[-1]
        assert second["memory"]["source_item_id"] == item_id
        assert len(repo.list_items()) == 2


def test_same_id_changed_identity_invalidates_old_item(queue, tmp_path):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        decide(repo, item_id)
    coverage(path, [ad(model="F 700 R")], tmp_path / "changed")
    with ReviewRepository(path) as repo:
        old = repo.show(item_id)
        assert old["state"] == "invalidated" and not old["active"]
        assert old["effective"]["scanner_key"] is None
        assert len(repo.list_items()) == 1
        assert len(repo.list_items(include_inactive=True)) == 2
        with pytest.raises(ValueError):
            decide(repo, item_id)


def test_price_change_does_not_create_new_item(queue, tmp_path):
    path, item_id = queue
    coverage(path, [ad(price="12345.00")], tmp_path / "price")
    with ReviewRepository(path) as repo:
        assert len(repo.list_items()) == 1
        assert repo.show(item_id)["advertisement"]["price"] == "12345.00"
    delta = collection_changes(2, path)
    assert delta["identity_changed"] == 0 and delta["data_changed"] == 1


def test_shared_latest_confirmation_overrides_previous(queue, tmp_path):
    path, item_id = queue
    import_base(path, [motorcycle()])
    build_coverage(1, path, tmp_path / "explicit")
    coverage(path, [ad(external_id="2")], tmp_path / "second")
    with ReviewRepository(path) as repo:
        decide(repo, item_id, "NAO_EXISTE_NA_BASE", None)
        second_id = repo.list_items()[-1]["id"]
        decide(repo, second_id)
        assert repo.show(item_id)["effective"]["scanner_key"] == "BMW|F900R|2025"
        assert len(repo.show(item_id)["history"]) == 2


def test_decision_transaction_rolls_back_on_projection_failure(queue, monkeypatch):
    path, item_id = queue
    with ReviewRepository(path) as repo:

        def fail(*args):
            raise RuntimeError("Injected failure after insert")

        monkeypatch.setattr(repo, "_refresh", fail)
        with pytest.raises(RuntimeError):
            decide(repo, item_id)
        assert repo.connection.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 0
        assert repo._item(item_id)["state"] == "pending"


def test_sync_transaction_rolls_back_partial_batch(queue):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        run_id = repo.show(item_id)["run_id"]
        original = repo.connection.execute("SELECT * FROM review_items").fetchall()
        with pytest.raises(ValueError):
            repo.sync(1, [(asdict(ad()), run_id), (asdict(ad(external_id="missing")), run_id)])
        assert repo.connection.execute("SELECT * FROM review_items").fetchall() == original


@pytest.mark.parametrize(
    "statement", ["UPDATE review_decisions SET note='overwritten'", "DELETE FROM review_decisions"]
)
def test_decision_audit_is_append_only(queue, statement):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        decide(repo, item_id)
        with pytest.raises(sqlite3.IntegrityError), repo.connection:
            repo.connection.execute(statement)
        assert len(repo.show(item_id)["history"]) == 1


def test_migration_from_v5_preserves_data_and_reopens(tmp_path):
    path = tmp_path / "v5.sqlite3"
    with sqlite3.connect(path) as conn:
        for migration in sorted(Path("database/migrations").glob("00[1-5]*.sql")):
            conn.executescript(migration.read_text(encoding="utf-8"))
            conn.execute("INSERT OR IGNORE INTO schema_version VALUES (?)", (int(migration.name[:3]),))
        conn.execute("INSERT INTO imports VALUES(1,'now','untouched','hash','{}','{}','{}')")
    for _ in range(2):
        with ReviewRepository(path) as repo:
            assert repo.connection.execute("SELECT source_path FROM imports").fetchone()[0] == "untouched"
            assert repo.connection.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 6
            assert repo.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert not repo.connection.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("command", ["list", "show", "history", "confirm", "reject", "no-match", "defer", "ignore"])
def test_cli_operational_commands(queue, command):
    path, item_id = queue
    args = [sys.executable, "-m", "app.review_queue", "--db", str(path), "--json", command]
    if command != "list":
        args.append(str(item_id))
    if command in {"confirm", "reject", "no-match", "defer", "ignore"}:
        args += ["--reviewer", "Fixture", "--note", "Reviewed fixture"]
    if command in {"confirm", "reject"}:
        args += ["--candidate", "BMW|F900R|2025"]
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)


def test_cli_missing_reviewer_and_missing_item_fail(queue):
    path, item_id = queue
    for tail in [["confirm", str(item_id), "--candidate", "BMW|F900R|2025", "--note", "x"], ["show", "9999"]]:
        result = subprocess.run(
            [sys.executable, "-m", "app.review_queue", "--db", str(path), *tail], capture_output=True
        )
        assert result.returncode == 2


def test_priority_filters_and_coverage_status(queue):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        assert repo.list_items(status="pending", requested_priority="medium")
        assert not repo.list_items(requested_priority="high")
    policy = load_policy()
    for status in ["SEM_SUPORTE", "SUPORTE_PARCIAL"]:
        assert priority({"match_type": "EXATO_NORMALIZADO", "scanner_status": status}, "pending", policy) == "high"


def test_partial_collection_cannot_report_disappearance(queue):
    path, _ = queue
    cid = collect(path, [], complete=False)
    assert collection_changes(cid, path)["disappeared"] is None


def test_no_identity_shared_decision_rejected(tmp_path):
    path = tmp_path / "db.sqlite3"
    import_base(path, [motorcycle()])
    report = coverage(path, [ad(year=None)], tmp_path / "report")
    item_id = report["groups"]["REVISAR"][0]["review_item_id"]
    with ReviewRepository(path) as repo:
        with pytest.raises(ValueError):
            decide(repo, item_id, "NAO_EXISTE_NA_BASE", None)
        assert decide(repo, item_id, "DEIXAR_PENDENTE", None)["state"] == "deferred"


def test_rejection_memory_reused_and_accumulates(queue, tmp_path):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        decide(repo, item_id, "REJEITAR_CANDIDATO")
        decide(repo, item_id, "REJEITAR_CANDIDATO", "BMW|F900RGT|2025")
    report = coverage(path, [ad()], tmp_path / "reject")
    item = report["groups"]["REVISAR"][0]
    assert item["effective_result"]["candidates"] == []
    assert item["effective_result"]["scanner_key"] is None
    assert report["review_queue"]["reused"] == 1


def test_fuzzy_cannot_override_human(queue, tmp_path):
    path, _ = queue
    source = ad(external_id="3", model="F 900 R GT EDITION")
    before = coverage(path, [source], tmp_path / "fuzzy")
    item = next(i for group in before["groups"].values() for i in group)
    assert item["automatic_result"]["scanner_key"] is None
    assert item["automatic_result"]["candidates"]
    with ReviewRepository(path) as repo:
        decide(repo, item["review_item_id"], candidate="BMW|F900RGT|2025")
    after = coverage(path, [source], tmp_path / "human")
    effective = next(i for group in after["groups"].values() for i in group)
    assert effective["automatic_result"] == item["automatic_result"]
    assert effective["effective_result"]["scanner_key"] == "BMW|F900RGT|2025"


def test_migration_failure_rolls_back_all_new_tables(tmp_path, monkeypatch):
    path = tmp_path / "migration.sqlite3"
    with sqlite3.connect(path) as conn:
        for migration in sorted(Path("database/migrations").glob("00[1-5]*.sql")):
            conn.executescript(migration.read_text(encoding="utf-8"))
            conn.execute("INSERT OR IGNORE INTO schema_version VALUES (?)", (int(migration.name[:3]),))
    original = Path.read_text

    def broken_sql(self, *args, **kwargs):
        text = original(self, *args, **kwargs)
        return text + "\nTHIS IS INVALID SQL;" if self.name == "006_review_queue.sql" else text

    monkeypatch.setattr(Path, "read_text", broken_sql)
    with pytest.raises(sqlite3.OperationalError):
        ReviewRepository(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 5
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'review_%'").fetchall()


def test_base_change_reopens_unreviewed_automatic_and_resolves_after_matching(queue, tmp_path):
    path, item_id = queue
    import_base(path, [motorcycle(status="SUPORTADO")])
    with ReviewRepository(path) as repo:
        assert repo.show(item_id)["state"] == "invalidated"
    coverage(path, [ad()], tmp_path / "new-base")
    with ReviewRepository(path) as repo:
        assert repo.show(item_id)["state"] == "resolved"
        assert repo.show(item_id)["human_decision"] is None


def test_old_collection_cannot_regress_queue_but_can_be_audited(queue, tmp_path):
    path, item_id = queue
    coverage(path, [ad(model="F 700 R")], tmp_path / "current")
    with pytest.raises(ValueError, match="Coleta anterior"):
        build_coverage(1, path, tmp_path / "wrong")
    report = build_coverage(1, path, tmp_path / "historical", update_queue=False)
    assert not report["operational_review_applied"]
    with ReviewRepository(path) as repo:
        assert repo.show(item_id)["state"] == "invalidated"


def test_cached_collection_reuses_item_without_new_last_seen(queue, tmp_path):
    path, item_id = queue
    with PartnerRepository(path) as repo:
        result = repo.get_collection(1)
        result.cached = True
        cid = repo.save_collection(result)
    build_coverage(cid, path, tmp_path / "cached")
    with ReviewRepository(path) as repo:
        assert len(repo.list_items()) == 1
        assert repo.show(item_id)["last_seen"] == ad().collected_at


@pytest.mark.parametrize("status", ["SUPORTADO", "SEM_SUPORTE", "SUPORTE_PARCIAL", "EM_ANALISE", "SEM_STATUS"])
def test_confirmation_never_invents_scanner_support(queue, status):
    path, item_id = queue
    import_base(path, [motorcycle(status=status)])
    with ReviewRepository(path) as repo:
        assert decide(repo, item_id)["effective"]["scanner_status"] == status


@pytest.mark.parametrize("target", [motorcycle(year=2024), motorcycle(manufacturer="HONDA")])
def test_current_key_cannot_cross_brand_or_year(queue, target):
    path, item_id = queue
    import_base(path, [target])
    with ReviewRepository(path) as repo:
        with pytest.raises(ValueError, match="incompatível"):
            decide(repo, item_id, candidate=target.key)


def test_human_readable_cli_and_filters(queue):
    path, item_id = queue
    result = subprocess.run(
        [sys.executable, "-m", "app.review_queue", "--db", str(path), "show", str(item_id)], capture_output=True
    )
    assert result.returncode == 0 and b"CANDIDATOS" in result.stdout and b"AUTOM" in result.stdout
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.review_queue",
            "--db",
            str(path),
            "--json",
            "list",
            "--status",
            "pending",
            "--priority",
            "high",
        ],
        capture_output=True,
    )
    assert result.returncode == 0 and json.loads(result.stdout) == []


def test_ambiguous_title_confirmation_is_specific_to_one_ad(queue, tmp_path):
    path, item_id = queue
    with ReviewRepository(path) as repo:
        item = decide(repo, item_id, candidate="BMW|F900RGT|2025")
        assert item["memory"]["scope"] == "advertisement"
    report = coverage(path, [ad(), ad(external_id="2")], tmp_path / "two-ads")
    assert report["review_queue"]["reused"] == 1
    assert report["counts"]["REVISAR"] == 1
    with ReviewRepository(path) as repo:
        other = repo.list_items()[-1]
        assert other["human_decision"] is None and other["state"] == "pending"


def test_new_base_ambiguity_prevents_cross_ad_confirmation(queue, tmp_path):
    path, item_id = queue
    import_base(path, [motorcycle()])
    build_coverage(1, path, tmp_path / "explicit")
    with ReviewRepository(path) as repo:
        assert decide(repo, item_id)["memory"]["scope"] == "identity"
    import_base(path, [motorcycle(), motorcycle("F 900 R GT")])
    report = coverage(path, [ad(external_id="2")], tmp_path / "ambiguous")
    assert report["review_queue"]["reused"] == 0
    assert report["counts"]["REVISAR"] == 1


def test_human_trim_correction_never_propagates_to_other_ids(queue, tmp_path):
    path, _ = queue
    source = ad(external_id="3", model="F 900 R GT EDITION")
    report = coverage(path, [source], tmp_path / "source")
    item_id = next(i for group in report["groups"].values() for i in group)["review_item_id"]
    with ReviewRepository(path) as repo:
        assert decide(repo, item_id, candidate="BMW|F900RGT|2025")["memory"]["scope"] == "advertisement"
    report = coverage(path, [replace(source, external_id="4")], tmp_path / "different-ad")
    assert report["review_queue"]["reused"] == 0
