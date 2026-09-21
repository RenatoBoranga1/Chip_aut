"""Read populated OOXML cells without materializing Excel's formatted area.

SAX traverses actual XML bytes (including serialized empty cells) in bounded
chunks; it never expands dimension/max_row into a million Python rows.
"""

import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.parsers import expat
from zipfile import ZipFile

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


@dataclass
class SheetData:
    name: str
    dimension: str = ""
    rows: list[tuple[int, dict[str, str]]] = field(default_factory=list)
    formulas: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class WorkbookData:
    sheets: list[SheetData]
    date1904: bool


def _xml(data: bytes):
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("XML com DTD/entidades não é aceito")
    return ET.fromstring(data)


def read_excel(path: str | Path) -> WorkbookData:
    with ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > 512 * 1024 * 1024:
            raise ValueError("XLSX excede limite de 512 MiB descompactado")
        workbook = _xml(archive.read("xl/workbook.xml"))
        relationships = _xml(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            r.attrib["Id"]: r.attrib["Target"] for r in relationships if r.attrib.get("TargetMode") != "External"
        }
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = _xml(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(t.text or "" for t in si.iter(f"{{{NS}}}t")) for si in root]
        sheets = []
        for node in workbook.findall(f"{{{NS}}}sheets/{{{NS}}}sheet"):
            target = targets[node.attrib[f"{{{REL}}}id"]]
            member = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            sheet = SheetData(node.attrib["name"])
            parser = expat.ParserCreate(namespace_separator="}")
            state = {"row": {}, "number": 0, "cell": None, "capture": False}

            def start(name, attrs):
                tag = name.rsplit("}", 1)[-1]
                if tag == "dimension":
                    sheet.dimension = attrs.get("ref", "")
                elif tag == "row":
                    state["number"] = int(attrs["r"])
                    state["row"] = {}
                elif tag == "c":
                    state["cell"] = {"ref": attrs["r"], "type": attrs.get("t"), "text": []}
                elif tag in {"v", "t"} and state["cell"] is not None:
                    state["capture"] = True
                elif tag == "f" and state["cell"] is not None:
                    sheet.formulas.append(state["cell"]["ref"])

            def text(value):
                if state["capture"]:
                    state["cell"]["text"].append(value)

            def end(name):
                tag = name.rsplit("}", 1)[-1]
                if tag in {"v", "t"}:
                    state["capture"] = False
                elif tag == "c":
                    cell = state["cell"]
                    value = "".join(cell["text"])
                    if cell["type"] == "s" and value:
                        value = strings[int(value)]
                    if cell["type"] == "e":
                        sheet.errors.append(cell["ref"])
                    if value.strip():
                        col = re.match(r"[A-Z]+", cell["ref"]).group()
                        state["row"][col] = value
                    state["cell"] = None
                elif tag == "row" and state["row"]:
                    sheet.rows.append((state["number"], state["row"]))

            def reject_doctype(*args):
                raise ValueError("XML com DTD não é aceito")

            parser.StartElementHandler = start
            parser.EndElementHandler = end
            parser.CharacterDataHandler = text
            parser.StartDoctypeDeclHandler = reject_doctype
            with archive.open(member) as stream:
                while chunk := stream.read(1024 * 1024):
                    parser.Parse(chunk, False)
                parser.Parse(b"", True)
            sheets.append(sheet)
        prop = workbook.find(f"{{{NS}}}workbookPr")
        epoch = prop is not None and prop.attrib.get("date1904") in {"1", "true"}
        return WorkbookData(sheets, epoch)
