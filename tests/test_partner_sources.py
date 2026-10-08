"""Alternative-source contracts use synthetic records and injected transport only."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.partners import main
from partners.registry import PartnerRegistry
from partners.sources import (
    audit_records,
    classify_record,
    dry_run,
    inspect_document,
    load_sources,
    public_url,
    source_notices,
)


def record(**changes):
    return dict(
        dict(
            external_id="123",
            manufacturer="Marca",
            model="Modelo",
            year=2026,
            detail_url="https://example.org/123",
            vehicle_type="motorcycle",
        ),
        **changes,
    )


def approved():
    return replace(
        load_sources("thomas_motos")[0],
        status="APPROVED",
        classification="DETERMINISTIC",
        audited_sample=10,
        false_positives=0,
    )


def test_sources_cannot_enable_registry():
    sources = load_sources()
    assert len(sources) == 6 and all(s.status != "APPROVED" for s in sources)
    assert [p.partner_key for p in PartnerRegistry().list(enabled_only=True)] == ["wr_motos"]
    marketplace = load_sources("moto_marques")[1]
    assert marketplace.identity == marketplace.trust == "UNVERIFIED"
    assert marketplace.observed_items == 27


@pytest.mark.parametrize(
    "changes",
    [
        dict(trust="UNVERIFIED"),
        dict(identity="UNVERIFIED"),
        dict(access="AUTH_REQUIRED"),
        dict(classification="UNAVAILABLE"),
        dict(audited_sample=9),
        dict(false_positives=1),
        dict(audited_sample=True),
        dict(unknown=-1),
    ],
)
def test_approval_requires_all_evidence(changes):
    with pytest.raises(ValueError):
        replace(approved(), **changes)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org",
        "https://user:password@example.org",
        "https://example.org/?token=private",
        "https://example.org/?api_key=private",
        "file:///tmp/x",
        "https://example.org/#secret",
    ],
)
def test_secret_or_nonpublic_metadata_rejected(url):
    with pytest.raises(ValueError):
        public_url(url)


@pytest.mark.parametrize(
    "row",
    [
        {"title": "HONDA 125 moto"},
        {"@type": "Vehicle"},
        {"@type": "Product"},
        {"category": "MOTOS", "category_id": 65},
        {"vehicle_type": "motorcycle", "item_type": "kart"},
        {"@type": ["Motorcycle"]},
    ],
)
def test_unknown_never_promoted_by_weak_fields(row):
    assert classify_record(row) == "UNKNOWN"


@pytest.mark.parametrize(
    "kind,body",
    [
        ("PUBLIC_API", json.dumps({"items": [record()]})),
        ("PUBLIC_JSON", json.dumps([record()])),
        ("FEED", "<rss><item><vehicle_type>motorcycle</vehicle_type></item></rss>"),
        ("HTML", '<script type="application/ld+json">{"@type":"Motorcycle"}</script>'),
        ("OFFICIAL_MARKETPLACE", '<script type="application/ld+json">{"@graph":[{"@type":"Motorcycle"}]}</script>'),
    ],
)
def test_structured_formats_are_offline_evidence_only(kind, body):
    result = inspect_document(body, kind)
    assert classify_record(result["records"][0]) == "MOTORCYCLE"
    assert not result["publishable"]


def test_sitemap_is_discovery_not_classification():
    result = inspect_document(
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.org/moto</loc></url></urlset>',
        "SITEMAP",
    )
    assert not result["records"] and result["discovery_urls"] == ["https://example.org/moto"]
    assert not result["publishable"]


@pytest.mark.parametrize(
    "kind,body",
    [
        ("PUBLIC_JSON", "{}"),
        ("PUBLIC_API", "[null]"),
        pytest.param("PUBLIC_JSON", "[]" * 1000001, id="oversize"),
        ("FEED", '<!DOCTYPE x [<!ENTITY y SYSTEM "file:///secret">]><x/>'),
    ],
)
def test_changed_or_unsafe_structure_rejected(kind, body):
    with pytest.raises(ValueError):
        inspect_document(body, kind)


def test_deduplication_invalid_identity_and_exclusion_reasons():
    rows = [
        record(),
        record(),
        record(external_id="2", vehicle_type="kart"),
        record(external_id="3", vehicle_type="service"),
        record(external_id="4", vehicle_type="car"),
        record(external_id="5", year="bad"),
        record(external_id="6", vehicle_type="Vehicle"),
        None,
    ]
    result = audit_records(approved(), rows)
    assert (
        result["motorcycles"]
        == result["duplicates"]
        == result["invalid_identity"]
        == result["unknown"]
        == result["parse_errors"]
        == 1
    )
    assert result["excluded"] == 3
    assert {r["reason"] for r in result["items"]} >= {
        "TYPE_KART",
        "TYPE_SERVICE",
        "TYPE_CAR",
        "TYPE_UNKNOWN",
        "DUPLICATE_ID",
        "INVALID_IDENTITY",
    }
    assert not result["eligible_batch"] and not result["publishable"]


def test_previously_approved_source_losing_type_is_degraded():
    result = audit_records(approved(), [record(vehicle_type="Vehicle")], previously_approved=True)
    assert result["status"] == "DEGRADED" and not result["eligible_batch"]
    assert "TYPE_CLASSIFICATION_UNAVAILABLE" in result["warning_codes"]
    assert audit_records(approved(), [record()])["eligible_batch"]
    assert not audit_records(load_sources()[0], [record()])["eligible_batch"]


def test_empty_batch_never_represents_valid_empty_inventory():
    assert "SOURCE_STRUCTURE_CHANGED" in audit_records(approved(), [])["warning_codes"]


def test_notices_deduplicate_without_suppressing_distinct_sources():
    sources = load_sources()
    assert source_notices(sources) == source_notices(sources + sources)
    assert {n["Código"] for n in source_notices(sources)} >= {
        "SOURCE_UNAVAILABLE",
        "ALTERNATIVE_SOURCE_FAILED",
        "TYPE_CLASSIFICATION_UNAVAILABLE",
    }


def test_dry_run_uses_bounded_diagnostic_and_never_persists(tmp_path, monkeypatch, capsys):
    calls = []

    def reader(url):
        calls.append(url)
        return (
            (404, "")
            if url.endswith("robots.txt")
            else (200, Path("tests/fixtures/partner_diagnostics/motonil_mixed.html").read_text(encoding="utf-8"))
        )

    monkeypatch.setattr("partners.diagnostics._read", reader)
    monkeypatch.setattr("app.partners.dry_run", lambda key: dry_run(key, sleeper=lambda _: None))
    absent = tmp_path / "absent.sqlite3"
    assert main(["collect", "motonil", "--dry-run", "--db", str(absent)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["unknown"] == result["raw_items"] == 3 and not result["publishable"]
    assert result["status"] == "BLOCKED" and len(calls) == 2 and not absent.exists()
    assert dry_run("moto_marques", reader=lambda _: pytest.fail("forbidden domain"))["raw_items"] is None


def test_sources_cli_and_invalid_collection(capsys):
    assert main(["sources", "thomas_motos"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 2
    assert main(["sources", "unlisted"]) == 1
    with pytest.raises(SystemExit):
        main(["collect", "motonil"])


def test_ui_shows_saved_sources_without_network(monkeypatch):
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("network"))
    app = AppTest.from_string(
        "from ui.partner_diagnostics import alternative_sources_panel\nalternative_sources_panel()"
    ).run(timeout=30)
    assert not app.exception
    assert len(app.expander) == 7
    content = " ".join(m.value for m in app.markdown)
    assert "dealer 3918827" in content and "75" in content and "19" in content
    assert "somente WR" in app.caption[0].value
