"""Public HTML XHR used by WR's own catalog; no authentication or bypass."""

import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from partners.access import USER_AGENT, AccessDeniedError, check_status, robots_policy
from partners.models import CatalogPage
from partners.wr_parser import BRANDS_PATH, CATALOG_URL, LIST_PATH, ORIGIN, next_page_number, parse_brands


class WRHTTPSource:
    method = "HTTP direto + HTML XHR público + BeautifulSoup"
    required_scopes = {"0", "1"}

    def __init__(self, delay=2.0, timeout_ms=30000, max_pages=100, evidence_dir=None):
        if delay < 2 or timeout_ms <= 0 or max_pages < 1:
            raise ValueError("Delay mínimo 2s, timeout e limite de páginas positivos")
        self.delay, self.timeout_ms, self.max_pages = delay, timeout_ms, max_pages
        self.evidence_dir = Path(evidence_dir) if evidence_dir else None
        self.metadata, self.brands = {}, []

    def _request(self, session, method, url, **kwargs):
        time.sleep(self.delay)
        response = session.request(method, url, timeout=self.timeout_ms / 1000, allow_redirects=False, **kwargs)
        # The source declares UTF-8; requests defaults text/html without charset to Latin-1.
        response.encoding = "utf-8"
        check_status(response.status_code, response.text)
        if 300 <= response.status_code < 400:
            raise AccessDeniedError("Redirecionamento requer nova inspeção; sem seguir automaticamente")
        if response.status_code != 200:
            raise RuntimeError(f"Resposta inesperada: HTTP {response.status_code}")
        return response

    def pages(self):
        self.metadata = {"completed_scopes": []}
        self.metadata["robots"] = robots_policy(ORIGIN, [CATALOG_URL, ORIGIN + LIST_PATH, ORIGIN + BRANDS_PATH])
        self.delay = max(self.delay, self.metadata["robots"]["delay"])
        with requests.Session() as session:
            session.headers.update({"User-Agent": USER_AGENT})
            landing = self._request(session, "GET", CATALOG_URL)
            soup = BeautifulSoup(landing.text, "html.parser")
            fields = soup.select('.form_busca input[name="zero_km"]')
            if {field.get("value") for field in fields} != self.required_scopes or LIST_PATH not in landing.text:
                raise RuntimeError("Contrato do catálogo mudou; revisar formulário/endpoints")
            self.metadata["terms_links"] = [
                a["href"]
                for a in soup.select("a[href]")
                if any(word in a.get_text().lower() for word in ("termos", "privacidade", "terms", "privacy"))
            ]
            self.brands = parse_brands(self._request(session, "POST", ORIGIN + BRANDS_PATH).text)
            if not self.brands:
                raise RuntimeError("Lista de marcas vazia")
            self.metadata["brands"] = self.brands
            count = 0
            for scope in ("0", "1"):
                number = 1
                while True:
                    if count >= self.max_pages:
                        raise RuntimeError("Limite de páginas atingido antes do fim dos dois filtros")
                    params = dict.fromkeys(("preco_de", "preco_ate", "marca", "modelo", "ano_de", "ano_ate"), "")
                    params.update(page=str(number), zero_km=scope)
                    response = self._request(session, "GET", ORIGIN + LIST_PATH, params=params)
                    count += 1
                    timestamp = datetime.now(timezone.utc).isoformat()
                    if self.evidence_dir:
                        self.evidence_dir.mkdir(parents=True, exist_ok=True)
                        (self.evidence_dir / f"scope-{scope}-page-{number}.html").write_text(
                            response.text, encoding="utf-8"
                        )
                    yield CatalogPage(scope, number, response.url, response.text, timestamp)
                    next_number = next_page_number(response.text, number)
                    if next_number is None:
                        self.metadata["completed_scopes"].append(scope)
                        break
                    number = next_number
