import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from partners.models import PartnerMotorcycle

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


def next_page_number(html, current):
    soup = BeautifulSoup(html, "html.parser")
    selected = soup.select_one(".paginacao .atual")
    if selected and selected.get_text(strip=True) != str(current):
        raise CatalogChangedError("Página retornada não corresponde à solicitada")
    following = [n for n in page_numbers(html) if n > current]
    if following:
        if min(following) != current + 1:
            raise CatalogChangedError("Paginação saltou uma página")
        return min(following)
    for a in soup.select(".paginacao a"):
        if re.search(r"pr[óo]xima|next", a.get_text(), re.I):
            raise CatalogChangedError("Controle de próxima página não avança")
    return None


def interpret_card(card, brands, timestamp):
    links = ([card] if card.name == "a" and card.get("href") else []) + card.select("a[href]")
    link = next((a for a in links if "veiculo=" in a["href"]), None)
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
    manufacturer, model, year = None, None, None
    warnings = []
    for brand in brands:
        prefix = re.match(re.escape(brand) + r"\s+", raw_name, re.I)
        if prefix:
            manufacturer = raw_name[: len(brand)]
            model = raw_name[prefix.end() :].strip()
            break
    if not manufacturer or not model:
        warnings.append("MARCA_OU_MODELO_NAO_INTERPRETADO")
    match = re.search(r"\bAno\s*:\s*(\d{4}(?:\s*/\s*\d{2,4})?)\b", raw_text, re.I)
    if match:
        if re.fullmatch(r"\d{4}", match.group(1)) and 1885 <= int(match.group(1)) <= 2100:
            year = int(match.group(1))
        else:
            warnings.append("ANO_AMBIGUO")
    else:
        warnings.append("ANO_AUSENTE")
    price_field = card.select_one(".preco")
    # Promotional amounts inside headings (e.g. R$ 4.000 below FIPE) are not prices.
    detail_text = " ".join(
        str(t) for t in card.find_all(string=True) if not any(re.fullmatch(r"h[1-6]", p.name or "") for p in t.parents)
    )
    price_text = price_field.get_text(" ", strip=True) if price_field else detail_text
    price_match = re.search(r"R\$\s*([\d.]+(?:,\d{2})?)(?!\d)", price_text)
    mileage_match = re.search(r"\bKM\s*:\s*([\d.]+)\b", raw_text, re.I)
    price = price_match.group(1).replace(".", "").replace(",", ".") if price_match else None
    mileage = int(mileage_match.group(1).replace(".", "")) if mileage_match else None
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
        None,
        warnings,
        price=price,
        mileage=mileage,
        raw_data={"year": match.group(1) if match else None, "card_html": str(card)},
    )


def parse_catalog_page(html, brands, timestamp, aliases=None):
    """Extract source fields only. aliases is retained for call compatibility."""
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
        cards = [block for block in found.values() if not any(id(parent) in found for parent in block.parents)]
    if not cards:
        text = soup.get_text(" ", strip=True).upper()
        if re.search(r"(?:NENHUM|N[ÃA]O (?:FOI|FORAM)) (?:VE[ÍI]CULO|RESULTADO|REGISTRO)", text):
            return [], [], 0
        raise CatalogChangedError("Resposta sem anúncios e sem indicação explícita de catálogo vazio")
    advertisements, errors = [], []
    for position, card in enumerate(cards, 1):
        try:
            advertisements.append(interpret_card(card, brands, timestamp))
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
