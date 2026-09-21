import json
from copy import deepcopy
from pathlib import Path

import pytest

from database.partner_repository import PartnerRepository
from partners.access import AccessDeniedError, check_status, robots_policy
from partners.models import CatalogPage, CollectionResult
from partners.wr_motos import WRMotosCollector
from partners.wr_parser import CatalogChangedError, page_numbers, parse_brands, parse_catalog_page
from services.collection_service import collect_partners

FIXTURES = Path(__file__).parent / "fixtures" / "wr_motos"
STAMP = "2026-09-21T12:00:00+00:00"


@pytest.fixture
def html():
    return (FIXTURES / "page1.html").read_text(encoding="utf-8")


def brands():
    return parse_brands((FIXTURES / "brands.html").read_text(encoding="utf-8"))


def card(identifier="1", title="BMW F 900 R", year="2025", css="div-veiculo"):
    return f'<div class="{css}"><a href="/v1/veiculo?veiculo={identifier}"><h5>{title}</h5><div>Ano: {year}</div></a></div>'


def parse(html):
    return parse_catalog_page(html, brands(), STAMP, {"HARLEY-DAVIDSON": "HARLEY DAVIDSON"})


class FixtureSource:
    def __init__(self, pages, fail=False):
        self.payloads, self.fail = pages, fail
        self.brands = brands()
        self.metadata = {"fixture": True}

    def pages(self):
        for number, html in enumerate(self.payloads, 1):
            yield CatalogPage("0", number, f"https://www.wrmotos.com.br/?page={number}", html, STAMP)
        if self.fail:
            raise TimeoutError("Fixture: timeout na página seguinte")


def test_real_snapshot_normal_page(html):
    ads, errors, count = parse(html)
    assert len(ads) == count == 25 and not errors
    assert ads[0].external_id == "446236"
    assert ads[0].manufacturer == "BMW"
    assert ads[0].model == "R 1250 GS ADVENTURE PREMIUM RALLYE"
    assert ads[0].year == 2022
    assert ads[0].version is None
    assert ads[0].raw_text and ads[0].source_url.endswith("446236")
    assert "ADVENTURE" in ads[0].normalized_key
    assert page_numbers(html) == [2, 3, 4, 5, 6]


def test_pagination_and_individual_ads():
    result = WRMotosCollector(FixtureSource([card("1"), card("2")])).collect_motorcycles()
    assert result.complete and len(result.advertisements) == 2
    assert len({a.normalized_key for a in result.advertisements}) == 1


def test_duplicate_same_id_preserved_once():
    result = WRMotosCollector(FixtureSource([card("1"), card("1") + card("2")])).collect_motorcycles()
    assert result.complete and len(result.advertisements) == 2
    assert result.metadata["duplicate_occurrences"] == 1


def test_conflicting_same_id_is_incomplete():
    result = WRMotosCollector(FixtureSource([card("1"), card("1", year="2024")])).collect_motorcycles()
    assert not result.complete and result.errors[0]["code"] == "CONFLICTING_AD"


def test_missing_title_keeps_id_and_original_text():
    ads, errors, count = parse(card().replace("<h5>BMW F 900 R</h5>", ""))
    assert count == len(ads) == 1 and not errors
    assert ads[0].external_id == "1" and ads[0].model is None
    assert "MARCA_OU_MODELO_NAO_INTERPRETADO" in ads[0].parse_warnings


@pytest.mark.parametrize("year", ["", "2024/2025", "25"])
def test_unknown_year_not_invented(year):
    ads, _, _ = parse(card(year=year))
    assert ads[0].year is None and ads[0].normalized_key is None


def test_simple_html_class_and_heading_change():
    ads, errors, count = parse(card(css="vehicle-card").replace("h5", "h3"))
    assert count == len(ads) == 1 and ads[0].year == 2025 and not errors


def test_missing_id_recorded():
    ads, errors, count = parse(card(identifier="").replace("veiculo=", "item="))
    assert count == 1 and not ads and errors[0]["code"] == "UNPARSED_CARD"


def test_empty_response_is_not_empty_catalog():
    with pytest.raises(CatalogChangedError):
        parse("<html>Site temporariamente indisponível</html>")
    assert parse("<div>Nenhum veículo encontrado</div>") == ([], [], 0)


def test_source_failure_keeps_partial_ads():
    result = WRMotosCollector(FixtureSource([card()], fail=True)).collect_motorcycles()
    assert len(result.advertisements) == 1 and not result.complete
    assert result.errors[0]["code"] == "TimeoutError"


@pytest.mark.parametrize("status", [401, 403, 429])
def test_blocked_status_stops(status):
    with pytest.raises(AccessDeniedError):
        check_status(status)


def test_challenge_is_not_bypassed():
    with pytest.raises(AccessDeniedError):
        check_status(200, "Please verify you are human")


def test_robots_disallow_and_404(monkeypatch):
    class Response:
        status_code = 200
        text = "User-agent: *\nDisallow: /v1/\n"
        is_redirect = False
    monkeypatch.setattr("partners.access.requests.get", lambda *a, **kw: Response())
    with pytest.raises(AccessDeniedError):
        robots_policy("https://www.wrmotos.com.br", ["https://www.wrmotos.com.br/v1/estoque/"])
    Response.status_code = 404
    assert robots_policy("https://www.wrmotos.com.br", ["https://www.wrmotos.com.br/v1/estoque/"])["status"] == 404


def test_seen_missing_failed_and_cache_history(tmp_path):
    first = WRMotosCollector(FixtureSource([card("1") + card("2")])).collect_motorcycles()
    with PartnerRepository(tmp_path / "db.sqlite3") as repo:
        repo.save_collection(first)
        later = deepcopy(first)
        later.advertisements = later.advertisements[:1]
        later.advertisements[0].collected_at = "2026-09-22T12:00:00+00:00"
        repo.save_collection(later)
        row = repo.connection.execute("SELECT first_seen_at,last_seen_at,verification_count FROM partner_advertisements WHERE external_id='1'").fetchone()
        assert row == (STAMP, "2026-09-22T12:00:00+00:00", 2)
        assert repo.connection.execute("SELECT not_seen_in_latest_collection FROM partner_advertisements WHERE external_id='2'").fetchone()[0] == 1
        repo.save_collection(CollectionResult("wr_motos", STAMP, errors=[{"code": "TimeoutError"}]))
        assert repo.connection.execute("SELECT not_seen_in_latest_collection FROM partner_advertisements WHERE external_id='1'").fetchone()[0] == 0
        later.cached = True
        repo.save_collection(later)
        assert repo.connection.execute("SELECT verification_count FROM partner_advertisements WHERE external_id='1'").fetchone()[0] == 2
        assert repo.connection.execute("SELECT COUNT(*) FROM partner_observations").fetchone()[0] == 3


def test_cache_does_not_access_site(tmp_path):
    from datetime import datetime, timezone
    from dataclasses import asdict
    result = WRMotosCollector(FixtureSource([card()])).collect_motorcycles()
    result.collected_at = datetime.now(timezone.utc).isoformat()
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps(asdict(result)), encoding="utf-8")
    result = WRMotosCollector(FixtureSource([], fail=True), cache_file=cache).collect_motorcycles()
    assert result.cached and result.complete and len(result.advertisements) == 1


def test_partner_failure_does_not_stop_others(tmp_path):
    class Failed:
        def collect_motorcycles(self):
            raise RuntimeError("Fixture failure")
    collected = collect_partners({"broken": Failed(), "wr_motos": WRMotosCollector(FixtureSource([card()]))}, tmp_path / "db.sqlite3")
    assert not collected[0][1].complete and collected[1][1].complete
