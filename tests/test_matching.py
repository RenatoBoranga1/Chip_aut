import json
import sqlite3
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from database.matching_repository import MatchingRepository
from matching.fuzzy_matcher import combined_model
from matching.matcher import Matcher
from matching.models import MotorcycleQuery
from matching.rules import load_matching_rules
from scanner_base.models import Motorcycle, ParsedBase
from scanner_base.normalizer import normalize_model, normalized_key
from services.matching_service import match_motorcycle


def motorcycle(model="F 900 R", manufacturer="BMW", year=2025, status="SEM_STATUS"):
    return Motorcycle(
        key=normalized_key(manufacturer, model, year),
        manufacturer=manufacturer,
        model=model,
        year=year,
        normalized_model=normalize_model(model),
        status=status,
        system_count=1,
        record_count=1,
        supported_systems=[],
        unsupported_systems=[],
        analysis_systems=[],
        unknown_systems=["ABS"],
        latest_date=None,
        releases=[],
    )


def matcher(*motos, **rule_changes):
    return Matcher(list(motos), {"SEA-DOO": "SEADOO"}, replace(load_matching_rules(), **rule_changes))


@pytest.mark.parametrize("model", ["F900 R", "F 900R", "F-900-R", "f 900 r"])
def test_exact_bmw(model):
    result = matcher(motorcycle()).match(MotorcycleQuery(" bmw ", model, "2025.0"))
    assert result.match_type == "EXATO_NORMALIZADO"
    assert result.confidence == 100
    assert result.scanner_key == "BMW|F900R|2025"
    assert result.scanner_status == "SEM_STATUS"  # Identity confidence is not support.
    assert not result.requires_review


@pytest.mark.parametrize("model", ["V-Strom 650 XT", "V Strom DL650XT"])
def test_suzuki_reordered_is_possible_not_confirmed(model):
    target = motorcycle("DL 650 XT V-STROM", "SUZUKI", 2024, "SUPORTADO")
    result = matcher(target).match(MotorcycleQuery("Suzuki", model, 2024))
    assert result.match_type == "CORRESPONDENCIA_PROVAVEL"
    assert 88 <= result.confidence < 100
    assert result.requires_review and result.scanner_key is None and result.scanner_status is None
    assert result.candidates[0].scanner_key == target.key
    assert result.candidates[0].scanner_status == "SUPORTADO"
    assert set(result.candidates[0].components) == {"token_sort", "token_set", "compact"}


@pytest.mark.parametrize(
    "manufacturer,model,year",
    [
        ("HONDA", "F900 R", 2025),
        ("BMW", "F900 R", 2024),
        ("BMW", "F850 R", 2025),
        ("BMW", "F1000 R", 2025),
    ],
)
def test_manufacturer_year_and_displacement_are_hard_filters(manufacturer, model, year):
    result = matcher(motorcycle()).match(MotorcycleQuery(manufacturer, model, year))
    assert result.match_type == "NAO_ENCONTRADA_NA_BASE"
    assert result.scanner_key is None and result.confidence == 0
    assert not result.candidates


@pytest.mark.parametrize("model", ["F900 RS", "F900 RR", "F900 R+", "F900 R SPORT", "F900"])
def test_version_differences_never_confirm(model):
    result = matcher(motorcycle()).match(MotorcycleQuery("BMW", model, 2025))
    assert result.scanner_key is None
    assert result.match_type != "EXATO_NORMALIZADO"
    assert all(c.confidence < 100 for c in result.candidates)
    if result.candidates:
        assert result.requires_review
        assert "VERSAO_DIFERENTE_OU_INCOMPLETA" in result.candidates[0].blockers


def test_xt_and_standard_remain_distinct():
    result = matcher(motorcycle("DL 650 V-STROM", "SUZUKI")).match(MotorcycleQuery("SUZUKI", "V-Strom 650 XT", 2025))
    assert result.match_type == "REVISAR"
    assert result.candidates[0].blockers


def test_separate_version_prevents_wrong_exact():
    result = matcher(motorcycle("F900 R"), motorcycle("F900 R SPORT")).match(
        MotorcycleQuery("BMW", "F900 R", 2025, "SPORT")
    )
    assert result.scanner_key == "BMW|F900RSPORT|2025"
    assert combined_model("F900 R SPORT", "sport") == "F900 R SPORT"
    # R is not a duplicate of the final RR token.
    assert combined_model("F900 RR", "R") == "F900 RR R"


@pytest.mark.parametrize(
    "query",
    [
        MotorcycleQuery("", "F900 R", 2025),
        MotorcycleQuery("BMW", "", 2025),
        MotorcycleQuery("BMW", "---", 2025),
        MotorcycleQuery("BMW", "+/?", 2025),
        MotorcycleQuery("---", "F900 R", 2025),
        MotorcycleQuery("BMW", "F900 R", None),
        MotorcycleQuery("BMW", "F900 R", "2024/2025"),
        MotorcycleQuery("BMW", "F900 R", 2025.5),
    ],
)
def test_missing_or_ambiguous_fields_require_review(query):
    result = matcher(motorcycle()).match(query)
    assert result.match_type == "REVISAR"
    assert result.requires_review and result.normalized_key is None


def test_missing_displacement_does_not_become_probable():
    result = matcher(motorcycle("DL 650 XT V STROM", "SUZUKI")).match(MotorcycleQuery("SUZUKI", "DL XT V STROM", 2025))
    assert result.match_type == "REVISAR"
    assert "INFORMACAO_NUMERICA_AUSENTE" in result.candidates[0].blockers


def test_ambiguous_scores_checked_before_limit():
    a = motorcycle("DL 650 XT V STROM", "SUZUKI")
    b = motorcycle("V STROM DL 650 XT", "SUZUKI")
    result = matcher(a, b, max_candidates=1, ambiguity_margin=20).match(
        MotorcycleQuery("SUZUKI", "V STROM 650 XT", 2025)
    )
    assert result.match_type == "REVISAR"
    assert result.candidates_total == 2 and len(result.candidates) == 1
    assert any("margem" in reason for reason in result.reasons)


def test_candidate_order_is_deterministic():
    a = motorcycle("DL 650 XT V STROM", "SUZUKI")
    b = motorcycle("V STROM DL 650 XT", "SUZUKI")
    query = MotorcycleQuery("SUZUKI", "V STROM 650 XT", 2025)
    assert matcher(a, b).match(query) == matcher(b, a).match(query)


def test_threshold_changes_are_effective():
    target = motorcycle("DL 650 XT V STROM", "SUZUKI")
    query = MotorcycleQuery("SUZUKI", "V STROM 650 XT", 2025)
    assert matcher(target).match(query).match_type == "CORRESPONDENCIA_PROVAVEL"
    assert matcher(target, probable_threshold=98).match(query).match_type == "REVISAR"
    assert matcher(target, candidate_threshold=99, probable_threshold=99).match(query).candidates == []


@pytest.mark.parametrize(
    "changes",
    [
        {"candidate_threshold": 0},
        {"probable_threshold": 101},
        {"ambiguity_margin": 0},
        {"candidate_threshold": 95, "probable_threshold": 90},
        {"max_candidates": 0},
        {"max_candidates": True},
        {"version_penalty": -1},
        {"candidate_threshold": float("nan")},
        {"weights": {"token_sort": 1}},
        {"weights": {"token_sort": 1, "token_set": 1, "compact": 1}},
        {"protected_tokens": []},
    ],
)
def test_invalid_policy_rejected(changes):
    with pytest.raises(ValueError):
        replace(load_matching_rules(), **changes)


def test_empty_and_duplicate_identity_fail():
    with pytest.raises(ValueError, match="vazia"):
        matcher()
    with pytest.raises(ValueError, match="duplicada"):
        matcher(motorcycle(), motorcycle())


def test_aliases_and_nautical_categories():
    target = motorcycle("GTI 130", "SEADOO")
    assert matcher(target).match(MotorcycleQuery("SEA-DOO", "GTI130", 2025)).scanner_key == target.key
    result = matcher(motorcycle("FX 1800", "YAMAHA NAUTICA")).match(MotorcycleQuery("YAMAHA", "FX1800", 2025))
    assert result.scanner_key is None


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "test.sqlite3"
    with MatchingRepository(path) as repo:
        repo.save_import(
            ParsedBase(motorcycles=[motorcycle("DL 650 XT V-STROM", "SUZUKI", 2024, "SUPORTADO")]),
            "fixture.xlsx",
            "fixture",
            {"manufacturer_aliases": {"SUZUKI MOTOS": "SUZUKI"}},
            {},
        )
    return path


def test_review_persists_without_erasing_automatic_result(database):
    query = MotorcycleQuery("SUZUKI MOTOS", "V-Strom 650 XT", 2024)
    saved = match_motorcycle(query, database)
    with MatchingRepository(database) as repo:
        assert len(repo.pending_matches()) == 1
        candidate = saved["automatic_result"]["candidates"][0]["scanner_key"]
        reviewed = repo.review_match(saved["run_id"], candidate, "Revisor de teste", "Fixture confirmada")
        assert reviewed["automatic_result"] == saved["automatic_result"]
        assert reviewed["effective_result"]["scanner_key"] == candidate
        assert reviewed["effective_result"]["confidence"] is None
        assert not repo.pending_matches()
        corrected = repo.review_match(saved["run_id"], None, "Revisor de teste", "Correção de teste")
        assert len(corrected["reviews"]) == 2
        assert corrected["effective_result"]["match_type"] == "SEM_CORRESPONDENCIA_MANUAL"
    with MatchingRepository(database) as repo:
        assert len(repo.get_match(saved["run_id"])["reviews"]) == 2


def test_review_not_reused_for_new_run_or_new_base(database):
    query = MotorcycleQuery("SUZUKI", "V-Strom 650 XT", 2024)
    saved = match_motorcycle(query, database)
    candidate = saved["automatic_result"]["candidates"][0]["scanner_key"]
    with MatchingRepository(database) as repo:
        repo.review_match(saved["run_id"], candidate, "Teste", "Teste")
        repo.save_import(
            ParsedBase(motorcycles=[motorcycle("DL 650 XT V-STROM", "SUZUKI", 2024, "SEM_SUPORTE")]),
            "new.xlsx",
            "changed",
            {"manufacturer_aliases": {}},
            {},
        )
        historical = repo.get_match(saved["run_id"])
        assert not historical["is_current_base"]
        assert historical["effective_result"]["scanner_status"] == "SUPORTADO"
    current = match_motorcycle(query, database)
    assert current["import_id"] == 2
    assert current["effective_result"]["requires_review"]
    assert current["automatic_result"]["candidates"][0]["scanner_status"] == "SEM_SUPORTE"


def test_invalid_review_rolls_back(database):
    saved = match_motorcycle(MotorcycleQuery("SUZUKI", "V-Strom 650 XT", 2024), database)
    with MatchingRepository(database) as repo:
        with pytest.raises(ValueError, match="candidatos"):
            repo.review_match(saved["run_id"], "BMW|F900R|2025", "Teste", "Teste")
        with pytest.raises(ValueError, match="obrigatórios"):
            repo.review_match(saved["run_id"], None, "", "Teste")
        with pytest.raises(ValueError, match="não encontrado"):
            repo.get_match(999)
        assert repo.connection.execute("SELECT COUNT(*) FROM matching_reviews").fetchone()[0] == 0


def test_missing_db_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(ValueError, match="Banco não encontrado"):
        match_motorcycle(MotorcycleQuery("BMW", "F900 R", 2025), path)
    assert not path.exists()


def test_schema_migration_preserves_v1_and_is_idempotent(tmp_path):
    path = tmp_path / "v1.sqlite3"
    migration = Path("database/migrations/001_initial.sql").read_text(encoding="utf-8")
    with sqlite3.connect(path) as conn:
        conn.executescript(migration)
        conn.execute("INSERT INTO imports VALUES (1,'2026-09-21','original.xlsx','hash','{}','{}','{}')")
    for _ in range(2):
        with MatchingRepository(path) as repo:
            assert repo.connection.execute("SELECT source_path FROM imports").fetchone()[0] == "original.xlsx"
            assert repo.connection.execute("SELECT version FROM schema_version ORDER BY version").fetchall() == [
                (1,),
                (2,),
                (3,),
                (4,),
                (5,),
                (6,),
                (7,),
                (8,),
                (9,),
                (10,),
                (11,),
            ]
            assert repo.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert not repo.connection.execute("PRAGMA foreign_key_check").fetchall()


def test_cli_match_review_end_to_end(database, tmp_path):
    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", *args],
            text=True,
            capture_output=True,
            encoding="utf-8",
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )

    matched = run(
        "app.match",
        "--db",
        str(database),
        "--manufacturer",
        "SUZUKI",
        "--model",
        "V-Strom 650 XT",
        "--year",
        "2024",
        "--reports",
        str(tmp_path / "reports"),
    )
    assert matched.returncode == 0, matched.stderr
    saved = json.loads((tmp_path / "reports/match-0001.json").read_text(encoding="utf-8"))
    pending = run("app.review_match", "--db", str(database), "list")
    assert pending.returncode == 0 and len(json.loads(pending.stdout)) == 1
    key = saved["automatic_result"]["candidates"][0]["scanner_key"]
    reviewed = run(
        "app.review_match",
        "--db",
        str(database),
        "decide",
        "1",
        "--candidate",
        key,
        "--reviewer",
        "Teste",
        "--note",
        "Teste de integração",
    )
    assert reviewed.returncode == 0, reviewed.stderr
    shown = run("app.review_match", "--db", str(database), "show", "1")
    assert json.loads(shown.stdout)["effective_result"]["scanner_key"] == key
    failed = run("app.match", "--db", str(tmp_path / "missing.sqlite3"), "--manufacturer", "BMW", "--model", "F900 R")
    assert failed.returncode == 1 and "matching_failed" in failed.stderr


def test_serializable_result():
    result = matcher(motorcycle()).match(MotorcycleQuery("BMW", "F900 R", 2025))
    assert json.loads(json.dumps(asdict(result)))["confidence"] == 100
