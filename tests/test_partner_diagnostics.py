"""Only synthetic/minimal HTML and injected HTTP responses; never the public network."""

import json
from pathlib import Path

import pytest
import requests
import test_partner_architecture as fixtures
from streamlit.testing.v1 import AppTest

from app.partners import main
from partners.access import AccessDeniedError
from partners.diagnostics import _read, diagnose, inspect_catalog, notices, saved_diagnosis
from partners.registry import PartnerRegistry
from services.partner_service import partner_status

architecture = fixtures.architecture
FIXTURES = Path(__file__).parent / "fixtures" / "partner_diagnostics"


def html(partner):
    return (FIXTURES / ("thomas_mixed.html" if partner == "thomas_motos" else "motonil_mixed.html")).read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    "partner,ids", [("thomas_motos", ["5058456", "5534082", "2656970"]), ("motonil", ["1061", "1755", "1635"])]
)
def test_mixed_category_never_publishes_motorcycles(partner, ids):
    report = inspect_catalog(partner, html(partner))
    assert not report["partial"] and not report["structure_changed"]
    assert report["unknown_items"] == report["observed_items"] == 3
    assert report["valid_motorcycles"] == report["excluded_by_type"] == 0
    assert [r["external_id"] for r in report["items"]] == ids
    assert all(r["classification"] == "UNKNOWN" and not r["publishable"] for r in report["items"])
    assert all(r["source_url"].startswith("https://") for r in report["items"])
    assert not report["publishable"] and not report["classification_available"]


@pytest.mark.parametrize(
    "body", ["", "<html>Estrutura nova com 20 ofertas</html>", "<h4>mostrando 0 - 0 de 0 veículos.</h4>"]
)
def test_missing_cards_not_empty_inventory(body):
    result = inspect_catalog("thomas_motos", body)
    assert result["partial"] and result["structure_changed"]
    assert "STRUCTURE_CHANGED" in result["warning_codes"]


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace("5534082", "5058456"),
        lambda s: s.replace("5058456", "invalid"),
        lambda s: s.replace("Veiculo/spin/5058456/detalhes", "https://private.test/5058456/detalhes"),
        lambda s: s.replace("mostrando 1 - 3 de 3 veículos.", "sem total"),
    ],
)
def test_duplicate_missing_id_external_link_or_changed_counter_is_partial(change):
    result = inspect_catalog("thomas_motos", change(html("thomas_motos")))
    assert result["partial"] and result["structure_changed"]
    assert result["valid_motorcycles"] == 0


def test_more_pages_are_partial_not_automatically_followed():
    result = inspect_catalog("motonil", html("motonil").replace("do total de 3", "do total de 30"))
    assert result["partial"] and not result["structure_changed"]
    assert result["declared_total"] == 30 and result["observed_items"] == 3


@pytest.mark.parametrize(
    "status,body",
    [
        (403, ""),
        (401, ""),
        (429, ""),
        (200, "<title>Just a moment</title>"),
        (200, "captcha challenge"),
        (200, '<form action="/login"><input type="password"></form>'),
        (302, ""),
    ],
)
def test_access_controls_interrupt_inspection(status, body):
    with pytest.raises(AccessDeniedError):
        inspect_catalog("thomas_motos", body, status)


def test_saved_diagnose_does_not_touch_network_or_database(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("network"))
    absent = tmp_path / "absent.sqlite3"
    for key in ["thomas_motos", "motonil", "moto_marques"]:
        assert main(["diagnose", key, "--db", str(absent)]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["last_validation"] == "2026-10-05"
        assert not result["publishable"] and not result["enabled"]
    assert not absent.exists()


def test_marques_live_respects_already_verified_disallow():
    result = diagnose("moto_marques", live=True, reader=lambda _: pytest.fail("forbidden request"))
    assert result["http_status"] == 403
    assert "restrição explícita" in result["mode"]
    assert result["unknown_items"] is None


@pytest.mark.parametrize(
    "robots", [(403, ""), (200, "User-agent: *\nDisallow: /"), (302, ""), (200, "verify you are human")]
)
def test_robots_blocks_catalog_without_retry(robots):
    calls = []

    def reader(url):
        calls.append(url)
        return robots

    result = diagnose("motonil", live=True, reader=reader, sleeper=lambda _: pytest.fail("sleep after block"))
    assert len(calls) == 1 and calls[0].endswith("/robots.txt")
    assert result["warning_codes"] == ["ACCESS_RESTRICTED"]
    assert result["unknown_items"] is None


@pytest.mark.parametrize("partner", ["thomas_motos", "motonil"])
def test_live_is_bounded_and_does_not_follow_details_or_mutate_evaluation(partner):
    calls, delays = [], []
    before = saved_diagnosis(partner)

    def reader(url):
        calls.append(url)
        return (404, "") if url.endswith("robots.txt") else (200, html(partner))

    result = diagnose(partner, live=True, reader=reader, sleeper=delays.append)
    assert len(calls) == 2 and delays == [2]
    assert result["unknown_items"] == 3 and not result["publishable"]
    assert before == saved_diagnosis(partner)


def test_timeout_does_not_retry_or_replace_unknown_with_zero():
    calls = []

    def reader(url):
        calls.append(url)
        raise requests.Timeout("fixture")

    result = diagnose("thomas_motos", live=True, reader=reader)
    assert len(calls) == 1 and result["warning_codes"] == ["TIMEOUT"]
    assert result["observed_items"] is None and result["unknown_items"] is None


def test_current_http_status_and_robots_delay_are_visible():
    responses = iter([(200, "User-agent: *\nAllow: /\nCrawl-delay: 3"), (403, "")])
    delays = []
    result = diagnose("motonil", live=True, reader=lambda _: next(responses), sleeper=delays.append)
    assert result["http_status"] == 403 and delays == [3]
    assert result["access_stage"] == "catalog" and result["partial"]


def test_oversized_response_and_transport_options(monkeypatch):
    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_content(self, size):
            yield b"x" * 3_000_001

    captured = {}

    def get(url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(ValueError, match="limite"):
        _read("https://thomasmotos.com.br/Veiculos")
    assert captured["allow_redirects"] is False and captured["timeout"] == 10
    assert captured["headers"] == {"User-Agent": "MotoCoverageMonitor/0.3"}


def test_deduplicated_notices_do_not_create_operational_events(architecture):
    path, registry, _ = architecture
    before = path.read_bytes()
    diagnoses = [saved_diagnosis(p) for p in ("moto_marques", "thomas_motos", "motonil")]
    assert len(notices(diagnoses + diagnoses)) == 3
    rows = partner_status(path, registry, include_candidates=True)
    candidates = {r["partner"]: r for r in rows if r["integration_status"] == "Não integrado"}
    assert candidates["motonil"]["unknown_items"] == 19
    assert candidates["thomas_motos"]["unknown_items"] == 78
    assert candidates["moto_marques"]["unknown_items"] is None
    assert all(r["active_ads"] == 0 for r in candidates.values())
    assert path.read_bytes() == before
    assert [p.partner_key for p in PartnerRegistry().list(enabled_only=True)] == ["wr_motos"]


def test_dashboard_quality_and_notices_are_read_only(architecture, monkeypatch):
    path, _, _ = architecture
    monkeypatch.setenv("MOTO_DB", str(path))
    monkeypatch.setenv("MOTO_READ_ONLY", "1")
    before = path.read_bytes()
    app = AppTest.from_file(str(Path("app/dashboard.py").resolve()), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Parceiros").run()
    assert not app.exception
    assert "Última validação manual" in app.table[0].value.columns
    assert "Tipo desconhecido" in app.dataframe[0].value.columns
    assert "Moto Marques" in str(app.table[1].value)
    app.sidebar.radio[0].set_value("Alertas").run()
    assert not app.exception
    assert path.read_bytes() == before


def test_unobserved_alternative_not_accepted_as_diagnostic_target():
    with pytest.raises(ValueError):
        diagnose("https://localhost/admin", live=True)
    with pytest.raises(ValueError):
        inspect_catalog("moto_marques", "fake public page")
