import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from partners.models import PartnerMotorcycle
from scanner_base.normalizer import normalize_manufacturer, normalize_text, normalize_year, normalized_key

ORIGIN = "https://www.wrmotos.com.br"
CATALOG_URL = ORIGIN + "/v1/estoque/"
LIST_PATH = "/v1/LojaConectada/_includes/listaCarros.php"
BRANDS_PATH = "/v1/LojaConectada/_includes/listaMarcasModelos.php"


class CatalogChangedError(ValueError):
    pass


def parse_brands(html):
    soup = BeautifulSoup(html, "html.parser")
    return sorted(
        {o.get("value", "").strip() for o in soup.select("option[value]") if o.get("value", "").strip()},
        key=len,
        reverse=True,
    )


def page_numbers(html):
    soup = BeautifulSoup(html, "html.parser")
    return sorted(
        {
            int(m.group(1))
            for a in soup.select("a[onclick], a[href]")
            if (m := re.search(r"[?&]page=(\d+)", a.get("onclick", "") + a.get("href", "")))
        }
    )


def interpret_card(card, brands, timestamp, aliases):
    link = next((a for a in card.select("a[href]") if "veiculo=" in a["href"]), None)
    if link is None:
        raise ValueError("Anúncio sem ID/URL")
    parsed_url = urlparse(urljoin(ORIGIN, link["href"]))
    external_id = parse_qs(parsed_url.query).get("veiculo", [""])[0]
    if parsed_url.hostname != "www.wrmotos.com.br" or not external_id.isdigit():
        raise ValueError("ID ou URL de anúncio inválido")
    source_url = ORIGIN + "/v1/veiculo?veiculo=" + external_id
    title = card.find(re.compile(r"^h[1-6]$"))
    img = card.find("img", alt=True)
    raw_name = title.get_text(" ", strip=True) if title else img.get("alt", "").strip() if img else ""
    raw_text = card.get_text(" ", strip=True)
    manufacturer, model, year, key = None, None, None, None
    warnings = []
    for brand in brands:
        if normalize_text(raw_name).startswith(normalize_text(brand) + " "):
            manufacturer = normalize_manufacturer(brand, aliases)
            model = raw_name[len(brand) :].strip()
            break
    if not manufacturer or not model:
        warnings.append("MARCA_OU_MODELO_NAO_INTERPRETADO")
    match = re.search(r"\bAno\s*:\s*(\d{4}(?:\s*/\s*\d{2,4})?)\b", raw_text, re.I)
    if match:
        try:
            year = normalize_year(match.group(1))
        except ValueError:
            warnings.append("ANO_AMBIGUO")
    else:
        warnings.append("ANO_AUSENTE")
    if manufacturer and model and year:
        key = normalized_key(manufacturer, model, year)
    return PartnerMotorcycle(
        "wr_motos",
        external_id,
        manufacturer,
        model,
        None,
        year,
        raw_name,
        source_url,
        timestamp,
        raw_text,
        key,
        warnings,
    )


def parse_catalog_page(html, brands, timestamp, aliases):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".div-veiculo")
    if not cards:
        # Resilient to class renaming: locate the nearest block with a title and ID link.
        found = {}
        for a in soup.select('a[href*="veiculo="]'):
            block = a
            while block and block.name not in {"body", "html", "[document]"}:
                if block.find(re.compile(r"^h[1-6]$")):
                    found[id(block)] = block
                    break
                block = block.parent
        cards = list(found.values())
    if not cards:
        text = normalize_text(soup.get_text(" ", strip=True))
        if re.search(r"(?:NENHUM|NAO (?:FOI|FORAM)) (?:VEICULO|RESULTADO|REGISTRO)", text):
            return [], [], 0
        raise CatalogChangedError("Resposta sem anúncios e sem indicação explícita de catálogo vazio")
    advertisements, errors = [], []
    for position, card in enumerate(cards, 1):
        try:
            advertisements.append(interpret_card(card, brands, timestamp, aliases))
        except ValueError as exc:
            errors.append(
                {
                    "code": "UNPARSED_CARD",
                    "position": position,
                    "detail": str(exc),
                    "raw_text": card.get_text(" ", strip=True),
                }
            )
    return advertisements, errors, len(cards)
