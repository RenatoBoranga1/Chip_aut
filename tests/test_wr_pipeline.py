import json
from copy import deepcopy

import pytest
import requests
from test_partners import STAMP, FixtureSource, brands, card

from database.partner_repository import PartnerRepository
from partners.models import CatalogPage
from partners.wr_http import WRHTTPSource
from partners.wr_motos import WRMotosCollector
from partners.wr_parser import CatalogChangedError, next_page_number, parse_catalog_page
from services.coverage_service import build_coverage


class Scopes:
    brands = brands()
    metadata = {}

    def __init__(self, pages):
        self.payloads = pages

    def pages(self):
        for scope, number, html in self.payloads:
            yield CatalogPage(scope, number, "https://www.wrmotos.com.br/fixture", html, STAMP)


def test_raw_parser_does_not_normalize_aliases():
    ad = parse_catalog_page(
        card(title="HARLEY-DAVIDSON ROAD KING"), ["HARLEY-DAVIDSON"], STAMP, {"HARLEY-DAVIDSON": "CHANGED"}
    )[0][0]
    assert ad.manufacturer == "HARLEY-DAVIDSON" and ad.normalized_key is None


def test_price_mileage_and_audit():
    html = card().replace("</h5>", "</h5><div>R$ 96.990,50</div><div>KM: 30.447</div>")
    result = WRMotosCollector(FixtureSource([html])).collect_motorcycles()
    ad = result.advertisements[0]
    assert (ad.price, ad.mileage, ad.zero_km) == ("96990.50", 30447, False)
    assert ad.raw_data["card_html"] and ad.raw_data["response_sha256"]


@pytest.mark.parametrize("css", ["preco", "changed-price"])
def test_promotional_title_amount_is_not_the_price(css):
    html = card(title="BMW S 1000 R PROMOÇÃO R$ 4.000 ABAIXO DA FIPE").replace(
        "</h5>", f'</h5><div class="{css}">R$ 59.990</div>'
    )
    assert parse_catalog_page(html, brands(), STAMP)[0][0].price == "59990"


@pytest.mark.parametrize("status", ["SEM_SUPORTE", "SUPORTE_PARCIAL", "EM_ANALISE", "SEM_STATUS", "SUPORTADO"])
def test_coverage_exact_status_groups(tmp_path, status):
    from test_matching import motorcycle

    from scanner_base.models import ParsedBase

    path = tmp_path / "coverage.sqlite3"
    result = WRMotosCollector(FixtureSource([card()])).collect_motorcycles()
    with PartnerRepository(path) as repo:
        repo.save_import(
            ParsedBase(motorcycles=[motorcycle(status=status)]), "fixture", "hash", {"manufacturer_aliases": {}}, {}
        )
        collection_id = repo.save_collection(result)
    report = build_coverage(collection_id, path, tmp_path / "reports")
    assert report["counts"][status] == 1
    assert report["groups"][status][0]["matching"]["match_type"] == "EXATO_NORMALIZADO"


def test_coverage_ambiguous_keeps_original_type(tmp_path):
    from test_matching import motorcycle

    from scanner_base.models import ParsedBase

    path = tmp_path / "coverage.sqlite3"
    result = WRMotosCollector(FixtureSource([card(title="BMW R 1250 GS")])).collect_motorcycles()
    with PartnerRepository(path) as repo:
        repo.save_import(
            ParsedBase(motorcycles=[motorcycle("R 1250 GS"), motorcycle("R 1250 GS ADVENTURE")]),
            "fixture",
            "hash",
            {"manufacturer_aliases": {}},
            {},
        )
        collection_id = repo.save_collection(result)
    report = build_coverage(collection_id, path, tmp_path / "reports")
    assert report["counts"]["REVISAR"] == 1
    assert report["groups"]["REVISAR"][0]["matching"]["match_type"] == "AMBIGUOUS"


def test_both_filters_and_cross_filter_duplicate():
    result = WRMotosCollector(
        Scopes([("0", 1, card("1") + card("2")), ("1", 1, card("2") + card("3"))])
    ).collect_motorcycles()
    assert result.complete and len(result.advertisements) == 3
    assert result.metadata["scope_counts"] == {"0": {"cards": 2, "unique_ids": 2}, "1": {"cards": 2, "unique_ids": 2}}
    assert result.metadata["observed_cards"] == 4 and result.metadata["duplicate_occurrences"] == 1
    assert [a.zero_km for a in result.advertisements] == [False, None, True]
    assert result.advertisements[1].raw_data["duplicate_observations"]


def test_missing_scope_is_partial():
    result = WRMotosCollector(Scopes([("0", 1, card())])).collect_motorcycles()
    assert not result.complete and result.errors[-1]["code"] == "MISSING_SCOPE"


@pytest.mark.parametrize("second", [("0", 1, card()), ("0", 3, card("2")), ("0", 2, card()), ("0", 2, card() + " ")])
def test_non_advancing_pages_stop(second):
    result = WRMotosCollector(Scopes([("0", 1, card()), second])).collect_motorcycles()
    assert not result.complete and result.errors


@pytest.mark.parametrize(
    "html",
    [
        '<div class="paginacao"><a class="atual">1</a></div>',
        '<div class="paginacao"><a onclick="f(\'?page=2\')">Próxima</a></div>',
        '<a href="?page=4">4</a>',
    ],
)
def test_bad_pagination(html):
    with pytest.raises(CatalogChangedError):
        next_page_number(html, 2)


def test_renamed_full_fixture_preserves_card_count(html):
    ads, errors, count = parse_catalog_page(html.replace("div-veiculo", "vehicle"), brands(), STAMP)
    assert len(ads) == count == 25 and not errors


@pytest.fixture
def html():
    from test_partners import FIXTURES

    return (FIXTURES / "page1.html").read_text(encoding="utf-8")


class Response:
    def __init__(self, text, status=200, url="https://www.wrmotos.com.br/fixture"):
        self.text, self.status_code, self.url = text, status, url


def mock_http(monkeypatch, payloads):
    calls = []
    responses = iter(payloads)
    landing = (
        '<form class="form_busca"><input name="zero_km" value="0"><input name="zero_km" value="1"></form>'
        + "/v1/LojaConectada/_includes/listaCarros.php"
    )

    def request(self, method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/estoque/"):
            return Response(landing)
        if "listaMarcas" in url:
            return Response('<option value="BMW">BMW</option>')
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr("partners.wr_http.robots_policy", lambda *a: {"delay": 2})
    monkeypatch.setattr("partners.wr_http.time.sleep", lambda _: None)
    monkeypatch.setattr(requests.Session, "request", request)
    return calls


def test_http_pages_filters_and_limits(monkeypatch):
    calls = mock_http(
        monkeypatch, [Response(card("1") + '<a href="?page=2">2</a>'), Response(card("2")), Response(card("3"))]
    )
    result = WRMotosCollector(WRHTTPSource()).collect_motorcycles()
    assert result.complete and len(result.advertisements) == 3
    assert [(c[2]["params"]["page"], c[2]["params"]["zero_km"]) for c in calls[2:]] == [
        ("1", "0"),
        ("2", "0"),
        ("1", "1"),
    ]
    assert all(c[2]["allow_redirects"] is False for c in calls)
    mock_http(monkeypatch, [Response(card() + '<a href="?page=2">2</a>')])
    limited = WRMotosCollector(WRHTTPSource(max_pages=1)).collect_motorcycles()
    assert not limited.complete and len(limited.advertisements) == 1


@pytest.mark.parametrize(
    "response",
    [
        Response("oops", 500),
        Response("", 401),
        Response("", 403),
        Response("", 429),
        Response("", 302),
        Response("Please verify you are human"),
        Response(""),
        requests.Timeout("timeout"),
    ],
)
def test_http_failures_preserve_partial_and_stop(monkeypatch, response):
    calls = mock_http(monkeypatch, [Response(card() + '<a href="?page=2">2</a>'), response])
    result = WRMotosCollector(WRHTTPSource()).collect_motorcycles()
    assert not result.complete and len(result.advertisements) == 1 and result.errors
    assert len(calls) == 4


def test_partial_never_marks_missing_and_cached_snapshot_reopens(tmp_path):
    result = WRMotosCollector(FixtureSource([card("1") + card("2")])).collect_motorcycles()
    path = tmp_path / "db.sqlite3"
    with PartnerRepository(path) as repo:
        repo.save_collection(result)
        partial = deepcopy(result)
        partial.complete = False
        partial.advertisements.pop()
        repo.save_collection(partial)
        assert (
            repo.connection.execute("SELECT SUM(not_seen_in_latest_collection) FROM partner_advertisements").fetchone()[
                0
            ]
            == 0
        )
        result.cached = True
        cached_id = repo.save_collection(result)
    with PartnerRepository(path) as repo:
        assert len(repo.get_collection(cached_id).advertisements) == 2
        assert repo.connection.execute("SELECT SUM(verification_count) FROM partner_advertisements").fetchone()[0] == 3
        assert repo.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not repo.connection.execute("PRAGMA foreign_key_check").fetchall()


def test_coverage_preserves_probable_status_separation(tmp_path):
    from test_gate import seeded

    path = seeded(tmp_path)
    ads = (
        card("1", "SUZUKI V-Strom 650 XT", "2024")
        + card("2", "SUZUKI DL 650 XT V-STROM", "2024")
        + card("3", "SUZUKI UNKNOWN", "2024")
        + card("4", "SUZUKI UNKNOWN", "")
    )
    result = WRMotosCollector(FixtureSource([ads])).collect_motorcycles()
    with PartnerRepository(path) as repo:
        collection_id = repo.save_collection(result)
    report = build_coverage(collection_id, path, tmp_path / "report")
    assert report["advertisements"] == 4 and sum(report["counts"].values()) == 4
    probable = report["groups"]["CORRESPONDENCIA_PROVAVEL"][0]["matching"]
    assert probable["scanner_key"] is None and probable["scanner_status"] is None
    assert probable["candidates"][0]["scanner_status"]
    assert report["counts"]["NAO_ENCONTRADA_NA_BASE"] == report["counts"]["REVISAR"] == 1
    assert json.loads((tmp_path / "report/coverage.json").read_text(encoding="utf-8"))["collection_id"] == collection_id
    with PartnerRepository(path) as repo:
        assert repo.connection.execute("SELECT COUNT(*) FROM coverage_runs").fetchone()[0] == 1
