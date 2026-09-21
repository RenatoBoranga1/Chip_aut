import json
from dataclasses import replace

from test_matching import motorcycle

from database.matching_repository import MatchingRepository
from matching.matcher import Matcher
from matching.models import MotorcycleQuery
from matching.rules import load_matching_rules
from scanner_base.models import ParsedBase
from services.matching_service import match_many, match_motorcycle


def seeded(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with MatchingRepository(path) as repo:
        repo.save_import(
            ParsedBase(motorcycles=[motorcycle("DL 650 XT V-STROM", "SUZUKI", 2024)]),
            "fixture",
            "fixture",
            {"manufacturer_aliases": {}},
            {},
        )
    return path


def test_exact_base_name_can_be_ambiguous():
    models = [motorcycle("R 1250 GS"), motorcycle("R 1250 GS ADVENTURE")]
    engine = Matcher(models, {}, load_matching_rules())
    result = engine.match(MotorcycleQuery("BMW", "R1250GS", 2025))
    assert result.match_type == "AMBIGUOUS" and result.requires_review
    assert result.scanner_key is None and len(result.candidates) == 2
    assert models[0].key != models[1].key
    assert engine.match(MotorcycleQuery("BMW", "R1250GS ADVENTURE", 2025)).scanner_key == models[1].key


def test_persistent_confirmation_is_loaded_before_fuzzy(tmp_path, monkeypatch):
    path = seeded(tmp_path)
    query = MotorcycleQuery("SUZUKI", "V-Strom 650 XT", 2024)
    run = match_motorcycle(query, path)
    key = run["automatic_result"]["candidates"][0]["scanner_key"]
    with MatchingRepository(path) as repo:
        repo.remember_match(run["run_id"], key, "CONFIRMAR", "Teste", "Confirmação")

    def fail(*args, **kwargs):
        raise AssertionError("Fuzzy não deveria ser chamado")

    monkeypatch.setattr("matching.matcher.compare_features", fail)
    again = match_motorcycle(query, path)
    assert again["automatic_result"]["match_type"] == "CONFIRMADO_MANUALMENTE"
    assert again["automatic_result"]["scanner_key"] == key
    assert again["automatic_result"]["confidence"] is None


def test_rejection_and_revocation(tmp_path):
    path = seeded(tmp_path)
    query = MotorcycleQuery("SUZUKI", "V-Strom 650 XT", 2024)
    run = match_motorcycle(query, path)
    key = run["automatic_result"]["candidates"][0]["scanner_key"]
    with MatchingRepository(path) as repo:
        repo.remember_match(run["run_id"], key, "REJEITAR", "Teste", "Versão não corresponde")
    assert not match_motorcycle(query, path)["automatic_result"]["candidates"]
    with MatchingRepository(path) as repo:
        repo.remember_match(run["run_id"], key, "REVOGAR", "Teste", "Correção")
        assert repo.connection.execute("SELECT COUNT(*) FROM matching_memory").fetchone()[0] == 2
    assert match_motorcycle(query, path)["automatic_result"]["candidates"]


def test_batch_loads_snapshot_once(tmp_path, monkeypatch):
    path = seeded(tmp_path)
    calls = []
    original = MatchingRepository.matching_snapshot

    def counted(self):
        calls.append(1)
        return original(self)

    monkeypatch.setattr(MatchingRepository, "matching_snapshot", counted)
    queries = [MotorcycleQuery("SUZUKI", "V-Strom 650 XT", 2024)] * 100
    results = match_many(queries, path)
    assert len(results) == 100 and len(calls) == 1
    with MatchingRepository(path) as repo:
        assert repo.connection.execute("SELECT COUNT(*) FROM matching_runs").fetchone()[0] == 100


def test_top_candidates_and_explanation():
    models = [motorcycle("DL 650 XT V-STROM", "SUZUKI"), motorcycle("DL 650 V-STROM", "SUZUKI")]
    engine = Matcher(models, {}, replace(load_matching_rules(), max_candidates=5))
    result = engine.match(MotorcycleQuery("SUZUKI", "V-Strom 650 XT", 2025))
    assert len(result.candidates) == 2
    reasons = json.dumps(result.candidates[0].reasons, ensure_ascii=False)
    assert "650" in reasons and "Tokens comuns" in reasons and "Só na base: DL" in reasons
    assert "Soma ponderada" in reasons
