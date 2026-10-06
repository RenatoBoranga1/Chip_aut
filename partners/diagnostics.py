"""Bounded, read-only diagnostics. No collector, database, cookies or publication path."""

import re
import time
from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from partners.access import USER_AGENT, AccessDeniedError, check_status
from partners.assessments import CANDIDATES, VALIDATIONS

CATALOGS = {
    "thomas_motos": "https://thomasmotos.com.br/Veiculos",
    "motonil": "https://www.motonil.com.br/MOTOS",
}
MAX_BYTES = 3_000_000
MESSAGES = {
    "CLASSIFICATION_UNAVAILABLE": "Classificação de motocicletas indisponível; nenhum item será publicado.",
    "ACCESS_RESTRICTED": "Acesso restrito; diagnóstico interrompido sem contorno ou novas tentativas.",
    "STRUCTURE_CHANGED": "Possível mudança de estrutura; não interpretar como estoque vazio.",
    "PARTIAL_DIAGNOSTIC": "Diagnóstico parcial; não representa o catálogo completo.",
    "TIMEOUT": "Prazo de acesso excedido; nenhuma repetição automática.",
    "HTTP_ERROR": "Falha de acesso HTTP; nenhum anúncio alterado.",
}


def saved_diagnosis(partner):
    candidate = next((p for p in CANDIDATES if p["partner"] == partner), None)
    if candidate is None:
        raise ValueError("Diagnóstico disponível somente para os três candidatos avaliados")
    return deepcopy(
        {
            **candidate,
            **VALIDATIONS[partner],
            "mode": "Última avaliação salva; sem acesso à rede",
            "enabled": False,
            "publishable": False,
            "integration_status": "Não integrado",
        }
    )


def inspect_catalog(partner, html, status=200):
    """Inspect only the observed HTML contracts; a mixed category can never prove type."""
    if partner not in CATALOGS:
        raise ValueError("Catálogo não aprovado para diagnóstico HTTP")
    check_status(status, html)
    if status != 200:
        raise AccessDeniedError("Redirecionamento ou resposta sem catálogo requer inspeção manual")
    soup = BeautifulSoup(html, "html.parser")
    if soup.select('input[type="password"]'):
        raise AccessDeniedError("Possível login obrigatório; inspeção manual necessária")
    cards = soup.select(".result-item" if partner == "thomas_motos" else ".product-layout")
    text = soup.get_text(" ", strip=True)
    pattern = (
        r"mostrando\s+\d+\s*-\s*\d+\s+de\s+(\d+)\s+veículos"
        if partner == "thomas_motos"
        else r"Exibindo de \d+ a \d+ do total de (\d+)"
    )
    total = re.search(pattern, text, re.IGNORECASE)
    declared = int(total[1]) if total else None
    items = []
    malformed = 0
    seen = set()
    for card in cards:
        anchor = card.select_one(".result-item-title a" if partner == "thomas_motos" else ".product-name a")
        href = anchor.get("href", "") if anchor else ""
        url = urljoin(CATALOGS[partner], href)
        identifier = re.search(r"/([0-9]+)/detalhes(?:$|[?#])", url) if partner == "thomas_motos" else None
        if partner == "motonil":
            button = card.select_one('[onclick*="cart.add"]')
            identifier = re.search(r"cart\.add\(['\"]([0-9]+)['\"]", button.get("onclick", "")) if button else None
        expected_host = urlsplit(CATALOGS[partner]).hostname
        valid_url = urlsplit(url).scheme == "https" and urlsplit(url).hostname == expected_host
        if not identifier or not anchor or not href or not valid_url or identifier[1] in seen:
            malformed += 1
            continue
        seen.add(identifier[1])
        items.append(
            {
                "external_id": identifier[1],
                "source_url": url,
                "title": anchor.get_text(" ", strip=True),
                "classification": "UNKNOWN",
                "confidence_kind": "UNKNOWN",
                "publishable": False,
                "source_category": "65/MOTOS" if partner == "motonil" else "Motos (breadcrumb genérico)",
                "evidence": "Categoria mista reprovada na auditoria; não comprova tipo individual.",
            }
        )
    structure_changed = (
        not cards or malformed > 0 or declared is None or (declared is not None and declared < len(cards))
    )
    warnings = ["CLASSIFICATION_UNAVAILABLE"]
    if structure_changed:
        warnings.append("STRUCTURE_CHANGED")
    partial = structure_changed or declared != len(cards)
    if partial:
        warnings.append("PARTIAL_DIAGNOSTIC")
    return {
        "http_status": status,
        "observed_items": len(cards),
        "declared_total": declared,
        "unknown_items": len(cards),
        "excluded_by_type": 0,
        "valid_motorcycles": 0,
        "classification_failures": malformed,
        "diagnostic_errors": int(structure_changed),
        "partial": partial,
        "structure_changed": structure_changed,
        "items": items,
        "warning_codes": warnings,
        "publishable": False,
        "safe_category": False,
        "classification_available": False,
        "catalog_found": bool(cards),
    }


def _read(url):
    with requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=10, allow_redirects=False, stream=True
    ) as response:
        # Stop on protection before reading or inspecting the body.
        if response.status_code != 200:
            return response.status_code, ""
        body = bytearray()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise ValueError("Resposta excede o limite diagnóstico")
        return response.status_code, body.decode("utf-8", errors="replace")


def diagnose(partner, *, live=False, reader=None, sleeper=time.sleep):
    result = saved_diagnosis(partner)
    if not live:
        return result
    if partner not in CATALOGS:
        result["mode"] = "Sem nova requisição: restrição explícita de robots já verificada"
        return result
    result.update(
        mode="Diagnóstico HTTP limitado; sem persistência",
        observed_items=None,
        unknown_items=None,
        valid_motorcycles=0,
        excluded_by_type=None,
        classification_failures=None,
        diagnostic_errors=0,
        http_status=None,
        catalog_found=None,
        warning_codes=[],
        last_manual_validation=result["last_validation"],
        partial=True,
    )
    reader = reader or _read
    url = CATALOGS[partner]
    origin = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
    try:
        try:
            status, policy = reader(origin + "/robots.txt")
        except RuntimeError as exc:
            if str(exc) not in {"HTTP 404", "HTTP 410"}:
                raise
            status, policy = int(str(exc).split()[1]), ""
        result["robots_http_status"] = status
        result["access_stage"] = "robots.txt"
        if status in {401, 403, 429}:
            result["http_status"] = status
        delay = 2
        if status not in {404, 410}:
            check_status(status, policy)
            if status != 200:
                raise AccessDeniedError("Redirecionamento de robots exige inspeção manual")
            parser = RobotFileParser()
            parser.parse(policy.splitlines())
            if not parser.can_fetch(USER_AGENT, url):
                raise AccessDeniedError("robots.txt não permite o catálogo")
            rate = parser.request_rate(USER_AGENT) or parser.request_rate("*")
            delay = max(
                2,
                parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or 0,
                rate.seconds / rate.requests if rate else 0,
            )
            if delay > 30:
                raise AccessDeniedError("Intervalo de robots exige diagnóstico manual")
        result["robots"] = "Política atual verificada" if status == 200 else "Não publicado; acesso limitado"
        sleeper(delay)
        result["access_stage"] = "catalog"
        status, html = reader(url)
        result["http_status"] = status
        result.update(inspect_catalog(partner, html, status))
    except (AccessDeniedError, requests.RequestException, RuntimeError, ValueError) as exc:
        code = (
            "ACCESS_RESTRICTED"
            if isinstance(exc, AccessDeniedError)
            else "TIMEOUT"
            if isinstance(exc, requests.Timeout)
            else "HTTP_ERROR"
        )
        result.update(warning_codes=[code], error=str(exc), diagnostic_errors=1)
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    # Live transport success is not manual approval and never changes the saved decision.
    return result


def notices(diagnoses):
    found = {}
    for item in diagnoses:
        for code in item.get("warning_codes", []):
            found[(item["partner"], code)] = {
                "Parceiro": item["display_name"],
                "Aviso": MESSAGES.get(code, code),
                "Validação": item.get("checked_at") or item.get("last_validation"),
            }
    return list(found.values())
