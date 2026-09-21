import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from partners.access import AccessDeniedError, check_status, is_catalog_response, robots_policy
from partners.models import CatalogPage
from partners.wr_parser import BRANDS_PATH, CATALOG_URL, LIST_PATH, ORIGIN, next_page_number, parse_brands

LOGGER = logging.getLogger(__name__)


class WRBrowserSource:
    method = "Playwright + HTML XHR público + BeautifulSoup"

    def __init__(self, channel=None, delay=2.0, timeout_ms=30000, max_pages=100, evidence_dir=None):
        if delay < 2 or timeout_ms <= 0 or max_pages < 1:
            raise ValueError("Delay mínimo 2s, timeout e limite de páginas positivos")
        self.channel, self.delay, self.timeout_ms = channel, delay, timeout_ms
        self.max_pages = max_pages
        self.evidence_dir = Path(evidence_dir) if evidence_dir else None
        self.metadata = {}
        self.brands = []

    def pages(self):
        self.metadata["robots"] = robots_policy(ORIGIN, [CATALOG_URL, ORIGIN + LIST_PATH, ORIGIN + BRANDS_PATH])
        delay = max(self.delay, self.metadata["robots"]["delay"])
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=self.channel, headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(self.timeout_ms)
                page.route(
                    "**/*",
                    lambda route: (
                        route.abort()
                        if route.request.resource_type in {"image", "media", "font"}
                        else route.continue_()
                    ),
                )

                def navigate():
                    with page.expect_response(is_catalog_response, timeout=self.timeout_ms) as waiting:
                        response = page.goto(CATALOG_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
                        if response:
                            check_status(response.status, response.text())
                    return waiting.value

                response = self._retry(navigate)
                page.wait_for_function("() => [...document.querySelectorAll('select.marca option')].some(o => o.value)")
                self.brands = parse_brands(page.locator("select.marca").inner_html())
                if not self.brands:
                    raise RuntimeError("Filtro de marcas não carregou")
                self.metadata["brands"] = self.brands
                self.metadata["catalog_url"] = CATALOG_URL
                self.metadata["terms_links"] = page.locator("a[href]").evaluate_all(
                    "els => els.filter(a => /termos|privacidade|terms|privacy/i.test(a.textContent)).map(a => a.href)"
                )
                count = 0
                for scope in ("0", "1"):
                    if scope == "1":
                        time.sleep(delay)

                        def change_scope():
                            with page.expect_response(is_catalog_response, timeout=self.timeout_ms) as waiting:
                                page.locator('input.zero_km[value="1"]').check()
                            return waiting.value

                        response = self._retry(change_scope)
                    number = 1
                    seen_pages = set()
                    while True:
                        count += 1
                        if count > self.max_pages:
                            raise RuntimeError("Limite de páginas atingido antes do fim do catálogo")
                        body = response.text()
                        check_status(response.status, body)
                        params = parse_qs(urlparse(response.url).query)
                        if params.get("page") != [str(number)] or params.get("zero_km") != [scope]:
                            raise RuntimeError("Resposta XHR não corresponde à página/filtro solicitado")
                        if number in seen_pages:
                            raise RuntimeError("Loop de paginação detectado")
                        seen_pages.add(number)
                        timestamp = datetime.now(timezone.utc).isoformat()
                        if self.evidence_dir:
                            self.evidence_dir.mkdir(parents=True, exist_ok=True)
                            (self.evidence_dir / f"scope-{scope}-page-{number}.html").write_text(body, encoding="utf-8")
                        LOGGER.info(
                            json.dumps({"event": "catalog_page", "scope": scope, "page": number, "bytes": len(body)})
                        )
                        yield CatalogPage(scope, number, response.url, body, timestamp)
                        # Wait for the corresponding HTML to reach the DOM before clicking.
                        page.wait_for_function("() => !document.querySelector('.estoque-lista img[src*=loader]')")
                        following_number = next_page_number(body, number)
                        if following_number is None:
                            break
                        number = following_number
                        time.sleep(delay)

                        def next_page():
                            with page.expect_response(is_catalog_response, timeout=self.timeout_ms) as waiting:
                                page.locator(".paginacao").get_by_role("link", name=str(number), exact=True).click()
                            return waiting.value

                        response = self._retry(next_page)
            finally:
                browser.close()

    @staticmethod
    def _retry(operation):
        for attempt in range(2):
            try:
                return operation()
            except AccessDeniedError:
                raise
            except PlaywrightTimeoutError:
                LOGGER.exception("catalog_timeout attempt=%s", attempt + 1)
                if attempt:
                    raise
                time.sleep(2)
