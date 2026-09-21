import logging
from pathlib import Path

import rapidfuzz

from database.matching_repository import MatchingRepository
from database.repository import encode
from matching.matcher import Matcher
from matching.models import MotorcycleQuery
from matching.rules import DEFAULT_MATCHING_RULES, load_matching_rules

LOGGER = logging.getLogger(__name__)


def match_motorcycle(query: MotorcycleQuery, database: Path, rules_path: Path = DEFAULT_MATCHING_RULES) -> dict:
    if not database.is_file():
        raise ValueError("Banco não encontrado; importe a base antes de executar o matching")
    rules = load_matching_rules(rules_path)
    with MatchingRepository(database) as repository:
        import_id, scanner_policy, motorcycles = repository.matching_snapshot()
        aliases = scanner_policy["manufacturer_aliases"]
        matcher = Matcher(motorcycles, aliases, rules, repository.load_memory())
        result = matcher.match(query)
        policy = {
            "algorithm_version": "3.1",
            "rapidfuzz_version": rapidfuzz.__version__,
            "matching_rules": rules.to_dict(),
            "manufacturer_aliases": aliases,
        }
        run_id = repository.save_match(import_id, policy, result)
        saved = repository.get_match(run_id)
    LOGGER.info(
        encode(
            {
                "event": "matching_completed",
                "run_id": run_id,
                "import_id": import_id,
                "match_type": result.match_type,
                "requires_review": result.requires_review,
                "candidates": result.candidates_total,
            }
        )
    )
    return saved


def match_many(queries, database: Path, rules_path: Path = DEFAULT_MATCHING_RULES):
    if not database.is_file():
        raise ValueError("Banco não encontrado")
    rules = load_matching_rules(rules_path)
    with MatchingRepository(database) as repo:
        import_id, scanner_policy, motorcycles = repo.matching_snapshot()
        memory = repo.load_memory()
        matcher = Matcher(motorcycles, scanner_policy["manufacturer_aliases"], rules, memory)
        results = matcher.match_many(queries)
        policy = {
            "algorithm_version": "3.1",
            "rapidfuzz_version": rapidfuzz.__version__,
            "matching_rules": rules.to_dict(),
            "manufacturer_aliases": scanner_policy["manufacturer_aliases"],
        }
        ids = repo.save_matches(import_id, policy, results)
    return [{"run_id": run_id, "import_id": import_id, "result": result} for run_id, result in zip(ids, results)]
