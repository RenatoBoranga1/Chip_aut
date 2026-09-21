from copy import deepcopy
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

from database.repository import SQLiteRepository, snapshot_diff
from scanner_base.aggregator import consolidate
from scanner_base.excel_reader import SheetData, WorkbookData, read_excel
from scanner_base.normalizer import normalize_manufacturer, normalize_model, normalize_year
from scanner_base.parser import parse_date, parse_workbook
from scanner_base.status import aggregate_status, classify
from services.import_service import import_base, load_rules
from services.report_service import write_reports

HEADERS = dict(
    zip("ABCDEFGHI", ["LANC.", "DATA", "MONTADORA", "MODELO", "ANO", "SISTEMA", "CABO", "LOCALIZACAO CABO", "SIT."])
)


def row(**changes):
    result = dict(zip("ABCDEFGHI", ["Sim", "44368", "BMW", "F 900R", "2025", "ABS", "CABO", "BANCO", "OK"]))
    result.update(changes)
    return result


def parsed(rows):
    sheet = SheetData("Base", rows=[(1, HEADERS)] + list(enumerate(rows, 2)))
    result = parse_workbook(WorkbookData([sheet], False), load_rules())
    consolidate(result)
    return result


def workbook_file(path, rows):
    book = Workbook()
    sheet = book.active
    sheet.append(list(HEADERS.values()))
    for record in rows:
        sheet.append([record.get(c) for c in "ABCDEFGHI"])
    book.save(path)
    return path


@pytest.mark.parametrize("name", ["F 900R", "F900 R", "F-900-R", "f–900–r"])
def test_equivalent_models(name):
    assert normalize_model(name) == "F900R"


@pytest.mark.parametrize("name", ["F 900 GS", "F 900 R+", "F 900 R SPORT", "F 900 R/RS"])
def test_preserves_versions(name):
    assert normalize_model(name) != normalize_model("F900R")


def test_manufacturer_aliases_and_categories():
    aliases = load_rules()["manufacturer_aliases"]
    assert normalize_manufacturer(" Sea-Doo ", aliases) == "SEADOO"
    assert normalize_manufacturer(" Yamaha Náutica ", aliases) == "YAMAHA NAUTICA"
    assert normalize_manufacturer("KAWASSAKI", aliases) == "KAWASSAKI"


@pytest.mark.parametrize("value", ["2024/2025", "25", "2025.5", "", "0", "2101"])
def test_rejects_ambiguous_year(value):
    with pytest.raises(ValueError):
        normalize_year(value)


def test_numeric_year():
    assert normalize_year("2025.0") == 2025


@pytest.mark.parametrize(
    "release,situation,expected",
    [
        ("Sim", "OK", "SUPORTADO"),
        ("sim", "", "SUPORTADO"),
        ("NÃO", "", "SEM_SUPORTE"),
        ("NÃO LANÇAR", "", "SEM_SUPORTE"),
        ("Sim", "ANALISE", "EM_ANALISE"),
        ("V16", "", "SEM_STATUS"),
        ("V16 MC", "", "SEM_STATUS"),
        ("Sim", "MC", "SEM_STATUS"),
        ("NÃO", "OK", "SEM_STATUS"),
        ("Sim", "VER ATUADORES", "SEM_STATUS"),
    ],
)
def test_status(release, situation, expected):
    assert classify(release, situation, load_rules())[0] == expected


@pytest.mark.parametrize(
    "values,expected",
    [
        (["SUPORTADO", "SEM_SUPORTE"], "SUPORTE_PARCIAL"),
        (["SUPORTADO", "EM_ANALISE"], "EM_ANALISE"),
        (["SUPORTADO", "SEM_STATUS"], "SEM_STATUS"),
        (["SUPORTADO", "SUPORTADO"], "SUPORTADO"),
        ([], "SEM_STATUS"),
    ],
)
def test_aggregated_status(values, expected):
    assert aggregate_status(values) == expected


def test_duplicates_and_consolidation():
    base = parsed([row(), row(), row(D="F900 R", F="PAINEL", A="NÃO", I="")])
    assert len(base.records) == 3
    assert base.records[1].duplicate_of == 0
    assert len(base.motorcycles) == 1
    assert base.motorcycles[0].system_count == 2
    assert base.motorcycles[0].status == "SUPORTE_PARCIAL"


def test_conflict_same_system_needs_review():
    base = parsed([row(), row(A="NÃO", I="")])
    assert base.motorcycles[0].status == "SEM_STATUS"
    assert any(i["code"] == "CONFLICTING_SYSTEM" for i in base.issues)


def test_incomplete_row_is_quarantined():
    base = parsed([row(), {"H": "CONECTOR EMBAIXO DO BANCO"}])
    assert len(base.records) == 1 and base.rejected_rows == 1
    assert base.issues[-1]["raw"]["H"] == "CONECTOR EMBAIXO DO BANCO"


def test_bad_date_retains_valid_identity():
    base = parsed([row(B="ontem")])
    assert base.records[0].date is None
    assert base.issues[0]["code"] == "INVALID_DATE"


def test_date_epochs():
    assert parse_date("44368", False) == "2021-06-21"
    assert parse_date("1", True) == "1904-01-02"
    assert parse_date("21/09/2026", False) == "2026-09-21"


def test_reordered_columns():
    new_headers = {"A": "SISTEMA", "B": "ANO", "C": "MODELO", "D": "MONTADORA"}
    sheet = SheetData("Base", rows=[(5, new_headers), (9, {"A": "ABS", "B": "2025", "C": "F900 R", "D": "BMW"})])
    base = parse_workbook(WorkbookData([sheet], False), load_rules())
    assert base.records[0].key == "BMW|F900R|2025"


def test_repeated_headers_and_extra_sheet():
    base = parse_workbook(
        WorkbookData(
            [
                SheetData("Notas", rows=[(1, {"A": "apenas notas"})]),
                SheetData("Base", rows=[(1, HEADERS), (2, row()), (3, HEADERS), (4, row(F="PAINEL"))]),
            ],
            False,
        ),
        load_rules(),
    )
    assert len(base.records) == 2
    assert any(i["code"] == "REPEATED_HEADER" for i in base.issues)


def test_sparse_excel_preserves_tail(tmp_path):
    path = workbook_file(tmp_path / "sparse.xlsx", [row()])
    with ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    contents["xl/worksheets/sheet1.xml"] = (
        contents["xl/worksheets/sheet1.xml"]
        .replace(
            b"</sheetData>",
            b'<row r="1048568"><c r="H1048568" t="inlineStr"><is><t>ORPHAN</t></is></c></row></sheetData>',
        )
        .replace(b"A1:I2", b"A1:AMJ1048568")
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    book = read_excel(path)
    assert len(book.sheets[0].rows) == 3
    assert book.sheets[0].rows[-1] == (1048568, {"H": "ORPHAN"})
    base = parse_workbook(book, load_rules())
    assert len(base.records) == 1 and base.rejected_rows == 1


def test_formula_rows_are_not_silently_trusted(tmp_path):
    path = workbook_file(tmp_path / "formula.xlsx", [row(), row(F="=1+1")])
    book = read_excel(path)
    base = parse_workbook(book, load_rules())
    assert base.rejected_rows == 1


def test_history_reimport_and_removal(tmp_path):
    path = workbook_file(tmp_path / "base.xlsx", [row(), row(D="F 850 GS")])
    database = tmp_path / "db.sqlite3"
    original_bytes = path.read_bytes()
    first, first_report = import_base(path, database)
    assert path.read_bytes() == original_bytes
    _, again = import_base(path, database)
    assert all(not v for v in again["diff"].values())
    workbook_file(path, [row(A="NÃO", I="")])
    _, last = import_base(path, database)
    assert last["diff"]["motorcycles_removed"] == ["BMW|F850GS|2025"]
    assert last["diff"]["status_changes"][0]["after"] == "SEM_SUPORTE"
    with SQLiteRepository(database) as repo:
        assert repo.connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 3
        assert repo.connection.execute("SELECT COUNT(*) FROM motorcycles").fetchone()[0] == 2
        assert len(repo.latest_snapshot()) == 1
        assert repo.connection.execute("SELECT COUNT(*) FROM system_records").fetchone()[0] == 5
    write_reports(first, first_report, tmp_path / "reports")
    assert (tmp_path / "reports/motorcycles.csv").exists()


def test_system_delta_does_not_treat_status_change_as_new_system():
    before = {"x": {"status": "SUPORTADO", "supported_systems": ["ABS"]}}
    after = {"x": {"status": "SEM_SUPORTE", "unsupported_systems": ["ABS"]}}
    diff = snapshot_diff(before, after)
    assert not diff["systems_added"] and not diff["systems_removed"]
    assert len(diff["status_changes"]) == 1


def test_transaction_rolls_back_on_invalid_record(tmp_path):
    base = parsed([row()])
    with SQLiteRepository(tmp_path / "db.sqlite3") as repo:
        repo.save_import(base, "file.xlsx", "hash", load_rules(), {})
        broken = deepcopy(base)
        broken.records.append(deepcopy(broken.records[0]))
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            repo.save_import(broken, "file.xlsx", "hash", load_rules(), {})
        assert repo.connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 1


def test_empty_import_fails_without_version(tmp_path):
    path = workbook_file(tmp_path / "empty.xlsx", [])
    database = tmp_path / "db.sqlite3"
    with pytest.raises(ValueError):
        import_base(path, database)
    assert not Path(database).exists()


def test_reordered_column_report_uses_original_manufacturer(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.append(["SISTEMA", "ANO", "MODELO", "MONTADORA"])
    sheet.append(["ABS", 2025, "F900R", " bmw "])
    path = tmp_path / "reordered.xlsx"
    book.save(path)
    _, report = import_base(path, tmp_path / "db.sqlite3")
    assert report["manufacturer_variants"] == {"BMW": [" bmw "]}


def test_duplicate_header_fails():
    headers = dict(HEADERS, J="MONTADORA")
    book = WorkbookData([SheetData("Base", rows=[(1, headers), (2, row())])], False)
    with pytest.raises(ValueError, match="Cabeçalho duplicado"):
        parse_workbook(book, load_rules())


def test_system_delta_normalizes_case_and_accents():
    before = {"x": {"status": "SUPORTADO", "supported_systems": ["Injeção"]}}
    after = {"x": {"status": "SUPORTADO", "supported_systems": ["INJECAO"]}}
    assert all(not value for value in snapshot_diff(before, after).values())


def test_shared_strings(tmp_path):
    path = workbook_file(tmp_path / "shared.xlsx", [row()])
    with ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    contents["xl/sharedStrings.xml"] = (
        b'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        b"<si><r><t>BM</t></r><r><t>W</t></r></si></sst>"
    )
    contents["xl/worksheets/sheet1.xml"] = contents["xl/worksheets/sheet1.xml"].replace(
        b'<c r="C2" t="inlineStr"><is><t>BMW</t></is></c>', b'<c r="C2" t="s"><v>0</v></c>'
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    assert read_excel(path).sheets[0].rows[1][1]["C"] == "BMW"
