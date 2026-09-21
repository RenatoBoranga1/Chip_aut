import logging
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

LOGGER = logging.getLogger(__name__)
USER_AGENT = "MotoCoverageMonitor/0.3"


class AccessDeniedError(RuntimeError):
    pass


def check_status(status, text=""):
    if status in {401, 403, 429}:
        raise AccessDeniedError(f"Acesso interrompido: HTTP {status}; sem contorno ou retry")
    lower = text.lower()
    if any(
        marker in lower
        for marker in (
            "verify you are human",
            "cf-chl-",
            "access denied",
            "captcha challenge",
            "checking your browser",
            "<title>just a moment",
        )
    ):
        raise AccessDeniedError("Desafio/bloqueio detectado; coleta interrompida")
    if status >= 400:
        raise RuntimeError(f"HTTP {status}")


def robots_policy(origin, targets, timeout=25):
    url = origin + "/robots.txt"
    for attempt in range(2):
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, allow_redirects=False)
            if response.status_code in {404, 410}:
                return {"url": url, "status": response.status_code, "delay": 2.0, "policy": "Não publicado"}
            check_status(response.status_code, response.text)
            if response.is_redirect:
                raise AccessDeniedError("Redirecionamento de robots.txt requer nova inspeção")
            parser = RobotFileParser(url)
            parser.parse(response.text.splitlines())
            if any(not parser.can_fetch(USER_AGENT, target) for target in targets):
                raise AccessDeniedError("robots.txt não permite os caminhos necessários")
            rate = parser.request_rate(USER_AGENT) or parser.request_rate("*")
            return {
                "url": url,
                "status": response.status_code,
                "delay": max(
                    2.0,
                    parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or 0,
                    rate.seconds / rate.requests if rate else 0,
                ),
                "policy": response.text,
            }
        except (requests.Timeout, requests.ConnectionError):
            if attempt:
                raise
            time.sleep(2)
    raise RuntimeError("Falha ao obter robots.txt")


def is_catalog_response(response):
    from partners.wr_parser import LIST_PATH

    return urlparse(response.url).path == LIST_PATH
