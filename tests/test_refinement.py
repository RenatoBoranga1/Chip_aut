import json
from copy import deepcopy
from dataclasses import replace

import pytest
from test_matching import motorcycle
from test_partners import FixtureSource, card

from database.matching_repository import MatchingRepository
from database.partner_repository import PartnerRepository
from matching.fuzzy_matcher import compare_features, features
from matching.identity import CATEGORIES, IdentityPolicy
from matching.matcher import Matcher
from matching.models import MotorcycleQuery
from matching.rules import load_matching_rules
from partners.wr_motos import WRMotosCollector
from scanner_base.models import ParsedBase
from services.coverage_service import build_coverage
from services.matching_service import match_motorcycle
from services.refinement_service import analyze_refinement, diagnostics, probable_absence

RULE_CASES = [
    ("yamaha-fazer-token-order", "YAMAHA", "FZ25 FAZER ABS", "FAZER FZ25 ABS"),
    ("ducati-streetfighter-spacing", "DUCATI", "STREETFIGHTER V4 S", "STREET FIGHTER V4 S"),
    ("ducati-scrambler-spelling", "DUCATI", "SCAMBLER FULL THROTTLE", "SCRAMBLER FULL THROTTLE"),
    ("bmw-adventure-rally-spelling", "BMW", "R 1250 GS ADVENTURE PREMIUM RALLY", "R 1250 GS ADVENTURE PREMIUM RALLYE"),
    ("bmw-40-years-translation", "BMW", "R 1250 GS ADVENTURE PREMIUM 40 ANOS", "R 1250 GS ADVENTURE PREMIUM 40 YEARS"),
    ("promotion-fipe-suffix", "BMW", "S 1000 R PROMOÇÃO R$4.000 ABAIXO DA FIPE", "S 1000 R"),
    ("promotion-star-suffix", "TRIUMPH", "SCRAMBLER 400 X ** PROMOÇÃO**", "SCRAMBLER 400 X"),
    ("repeated-manufacturer-prefix", "BMW", "BMW R 18", "R 18"),
    ("repeated-dct-description", "HONDA", "CRF 1100L AFRICA TWIN DCT *VERSÃO DCT*", "CRF 1100L AFRICA TWIN DCT"),
]


def test_every_configured_rule_has_evidence_and_explicit_regression():
    policy = load_matching_rules().identity_policy
    rules = [r for c in CATEGORIES for r in policy[c]]
    assert {r["id"] for r in rules} == {r[0] for r in RULE_CASES}
    assert all(r["evidence"] for r in rules)


@pytest.mark.parametrize("rule_id,brand,original,canonical", RULE_CASES)
def test_rule_positive_and_trace(rule_id, brand, original, canonical):
    rules = load_matching_rules()
    value, steps = IdentityPolicy(rules.identity_policy).model(brand, original)
    assert value == canonical
    assert rule_id in {s["rule_id"] for s in steps}
    target = motorcycle(canonical, brand, 2025)
    result = Matcher([target], {}, rules).match(MotorcycleQuery(brand, original, 2025))
    assert result.match_type == "EXATO_NORMALIZADO" and result.scanner_key == target.key
    assert result.query.model == original
    assert result.identity_evidence["query_steps"]


@pytest.mark.parametrize("rule_id,brand,original,canonical", RULE_CASES)
def test_rule_cannot_merge_years_or_variants(rule_id, brand, original, canonical):
    rules = load_matching_rules()
    engine = Matcher([motorcycle(canonical + " ADVENTURE", brand, 2025)], {}, rules)
    result = engine.match(MotorcycleQuery(brand, original, 2025))
    assert result.scanner_key is None and result.requires_review or result.match_type == "NAO_ENCONTRADA_NA_BASE"
    other_year = Matcher([motorcycle(canonical, brand, 2024)], {}, rules).match(MotorcycleQuery(brand, original, 2025))
    assert other_year.scanner_key is None


@pytest.mark.parametrize(
    "model",
    [
        "R 1250 GS ADVENTURE",
        "NOVA R 1250 GS",
        "R 1250 GS IMPECAVEL",
        "R 1250 GS *PREPARADO PARA 330CC*",
        "R 1250 GS *PSS LEILÃO*",
        "R 1250 GS *PROMOÇÃO ADVENTURE*",
        "R 1250 GS PROMOÇÃO",
        "R 1250 GS PROMOÇÃO R$4.000 ABAIXO DA FIPE ADVENTURE",
    ],
)
def test_unapproved_noise_not_removed(model):
    engine = Matcher([motorcycle("R 1250 GS")], {}, load_matching_rules())
    assert engine.match(MotorcycleQuery("BMW", model, 2025)).scanner_key is None


def test_dct_descriptor_requires_existing_dct():
    result = Matcher([motorcycle("CRF 1100L AFRICA TWIN", "HONDA")], {}, load_matching_rules()).match(
        MotorcycleQuery("HONDA", "CRF 1100L AFRICA TWIN *VERSÃO DCT*", 2025)
    )
    assert result.scanner_key is None


@pytest.mark.parametrize("rule_id,brand,original,canonical", RULE_CASES[:5])
def test_aliases_do_not_leak_to_other_manufacturers(rule_id, brand, original, canonical):
    _, steps = IdentityPolicy(load_matching_rules().identity_policy).model("OTHER", original)
    assert rule_id not in {s["rule_id"] for s in steps}


@pytest.mark.parametrize("token", load_matching_rules().identity_policy["protected_tokens"])
def test_every_additional_variant_token_blocks_probable(token):
    target = motorcycle("F 900 R " + token)
    candidate = compare_features(features("F 900 R"), target, features(target.model), load_matching_rules(), True)
    assert "VERSAO_DIFERENTE_OU_INCOMPLETA" in candidate.blockers
    assert candidate.confidence < load_matching_rules().probable_threshold


def test_alias_collision_does_not_choose_one_original_identity():
    models = [motorcycle("SCRAMBLER FULL THROTTLE", "DUCATI"), motorcycle("SCAMBLER FULL THROTTLE", "DUCATI")]
    result = Matcher(models, {}, load_matching_rules()).match(
        MotorcycleQuery("DUCATI", "SCRAMBLER FULL THROTTLE", 2025)
    )
    assert result.match_type == "AMBIGUOUS" and result.scanner_key is None
    assert {c.scanner_key for c in result.candidates} == {m.key for m in models}


@pytest.mark.parametrize("mutation", ["no_evidence", "duplicate_id", "no_scope", "unanchored_noise"])
def test_bad_alias_policy_rejected(mutation):
    policy = deepcopy(load_matching_rules().identity_policy)
    if mutation == "no_evidence":
        policy["model_aliases"][0].pop("evidence")
    elif mutation == "duplicate_id":
        policy["model_aliases"].append(policy["model_aliases"][0])
    elif mutation == "no_scope":
        policy["token_aliases"][0].pop("manufacturer")
    else:
        policy["noise_rules"][0]["pattern"] = ".*"
    with pytest.raises(ValueError):
        replace(load_matching_rules(), identity_policy=policy)


def test_scoped_manufacturer_alias_is_supported_without_new_production_mapping():
    policy = deepcopy(load_matching_rules().identity_policy)
    policy["manufacturer_aliases"] = [
        {"id": "synthetic-manufacturer", "from": "TEST-MAKE", "to": "TEST MAKE", "evidence": "Synthetic fixture only"}
    ]
    rules = replace(load_matching_rules(), identity_policy=policy)
    target = motorcycle("F 900 R", "TEST MAKE")
    result = Matcher([target], {}, rules).match(MotorcycleQuery("TEST-MAKE", "F 900 R", 2025))
    assert result.scanner_key == target.key
    assert result.identity_evidence["query_steps"][0]["rule_id"] == "synthetic-manufacturer"


def test_memory_uses_original_identity_context_not_noise_alias(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with MatchingRepository(path) as repo:
        repo.save_import(
            ParsedBase(motorcycles=[motorcycle("F 900 R"), motorcycle("F 900 R", year=2024)]),
            "fixture",
            "hash",
            {"manufacturer_aliases": {}},
            {},
        )
    query = MotorcycleQuery("BMW", "F 900 R *PROMOÇÃO*", 2025)
    run = match_motorcycle(query, path)
    key = run["automatic_result"]["scanner_key"]
    with MatchingRepository(path) as repo:
        repo.remember_match(run["run_id"], key, "CONFIRMAR", "Synthetic reviewer", "Fixture")
    assert match_motorcycle(query, path)["automatic_result"]["match_type"] == "CONFIRMADO_MANUALMENTE"
    assert (
        match_motorcycle(MotorcycleQuery("BMW", "F-900-R *PROMOÇÃO*", 2025), path)["automatic_result"]["match_type"]
        == "CONFIRMADO_MANUALMENTE"
    )
    for changed in [
        MotorcycleQuery("BMW", "F 900 R", 2025),
        MotorcycleQuery("BMW", "F 900 R *PROMOÇÃO*", 2024),
        MotorcycleQuery("BMW", "F 900 R *PROMOÇÃO*", 2025, "GT"),
    ]:
        assert match_motorcycle(changed, path)["automatic_result"]["match_type"] != "CONFIRMADO_MANUALMENTE"
    with MatchingRepository(path) as repo:
        saved = repo.get_match(run["run_id"])
        assert saved["policy"]["matching_rules"]["identity_policy"]["version"]
        assert repo.connection.execute("SELECT COUNT(*) FROM matching_memory").fetchone()[0] == 1


def test_memory_cannot_cross_manufacturer_or_year_even_with_invalid_external_state():
    target = motorcycle(year=2024)
    memory = {"BMW|F900R|2025": {target.key: "CONFIRMAR"}}
    result = Matcher([target], {}, load_matching_rules(), memory).match(MotorcycleQuery("BMW", "F 900 R", 2025))
    assert result.scanner_key is None


def test_absence_requires_specific_evidence_and_is_not_support():
    query = MotorcycleQuery("BMW", "F 900 R", 2025)
    engine = Matcher([motorcycle(year=2024)], {}, load_matching_rules())
    ad = {"manufacturer": "BMW", "model": "F 900 R", "year": 2025, "parse_warnings": []}
    after = {"match_type": "NAO_ENCONTRADA_NA_BASE"}
    assert probable_absence(ad, after, diagnostics(query, engine))
    assert (
        probable_absence(ad, after, diagnostics(query, Matcher([motorcycle("F 900 R GT")], {}, load_matching_rules())))
        is None
    )
    assert probable_absence({**ad, "parse_warnings": ["ANO_AMBIGUO"]}, after, diagnostics(query, engine)) is None
    assert probable_absence(ad, {"match_type": "REVISAR"}, diagnostics(query, engine)) is None


@pytest.mark.parametrize("field,value", [("near_similarity", float("nan")), ("max_candidates", 0)])
def test_invalid_diagnostic_policy_rejected(field, value):
    policy = deepcopy(load_matching_rules().identity_policy)
    policy["diagnostics"][field] = value
    with pytest.raises(ValueError):
        replace(load_matching_rules(), identity_policy=policy)


def test_missing_identity_remains_in_inventory_for_review(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with PartnerRepository(path) as repo:
        repo.save_import(ParsedBase(motorcycles=[motorcycle()]), "fixture", "hash", {"manufacturer_aliases": {}}, {})
        result = WRMotosCollector(FixtureSource([card(title="", year="")])).collect_motorcycles()
        cid = repo.save_collection(result)
    baseline = build_coverage(cid, path, tmp_path / "before")
    summary = analyze_refinement(cid, baseline["coverage_run_id"], path, tmp_path / "after")
    assert summary["after"] == {"REVISAR": 1}
    assert summary["probable_absence_count"] == 0


def test_inventory_before_after_ablation_and_immutable_inputs(tmp_path):
    path = tmp_path / "db.sqlite3"
    old_rules = tmp_path / "old.json"
    old_rules.write_text(json.dumps(replace(load_matching_rules(), identity_policy={}).to_dict()), encoding="utf-8")
    with PartnerRepository(path) as repo:
        repo.save_import(ParsedBase(motorcycles=[motorcycle()]), "fixture", "hash", {"manufacturer_aliases": {}}, {})
        result = WRMotosCollector(FixtureSource([card(title="BMW F 900 R *PROMOÇÃO*")])).collect_motorcycles()
        cid = repo.save_collection(result)
        original = repo.connection.execute("SELECT * FROM partner_advertisements").fetchall()
    before = build_coverage(cid, path, tmp_path / "before", old_rules)
    summary = analyze_refinement(cid, before["coverage_run_id"], path, tmp_path / "after")
    assert summary["resolved"] == 1
    assert summary["resolved_by_essential_rule"] == {"promotion-star-suffix": 1}
    inventory = json.loads((tmp_path / "after/inventory.json").read_text(encoding="utf-8"))["inventory"]
    assert inventory[0]["diagnostics"]["tokens"]
    assert inventory[0]["before"]["scanner_key"] is None
    assert inventory[0]["after"]["scanner_key"] == "BMW|F900R|2025"
    with PartnerRepository(path) as repo:
        assert repo.connection.execute("SELECT * FROM partner_advertisements").fetchall() == original
        repo.save_import(ParsedBase(motorcycles=[motorcycle()]), "fixture", "hash", {"manufacturer_aliases": {}}, {})
    with pytest.raises(ValueError, match="mesma coleta e versão"):
        analyze_refinement(cid, before["coverage_run_id"], path, tmp_path / "wrong")
