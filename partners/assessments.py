"""Assessment metadata is informational; never registers executable collectors."""

CANDIDATES = (
    {
        "partner": "moto_marques",
        "display_name": "Moto Marques Multimarcas",
        "url": "https://motomarquesmultimarcas.com.br/",
        "reason": "HTTP simples 403; navegador abre, mas robots.txt proíbe coleta (Disallow: /).",
    },
    {
        "partner": "thomas_motos",
        "display_name": "Thomas Motos",
        "url": "https://thomasmotos.com.br/Veiculos",
        "reason": "Estoque misto; breadcrumb Motos também no carro, sem tipo individual verificável.",
    },
    {
        "partner": "motonil",
        "display_name": "Motonil",
        "url": "https://www.motonil.com.br/MOTOS",
        "reason": "Categoria técnica 65/MOTOS inclui kart e serviço; sem tipo individual confiável.",
    },
)


def unintegrated(registry):
    configured = {p.partner_key for p in registry.list()}
    return [
        {**p, **VALIDATIONS[p["partner"]], "integration_status": "Não integrado", "enabled": False}
        for p in CANDIDATES
        if p["partner"] not in configured
    ]


# Dated evidence, not a live stock snapshot and never an executable registry entry.
VALIDATIONS = {
    "thomas_motos": {
        "last_validation": "2026-10-05",
        "validation_result": "DADOS INSUFICIENTES PARA CLASSIFICAÇÃO SEGURA",
        "method": "Diagnóstico HTTP/HTML e navegador; sem collector",
        "safe_category": False,
        "http_status": 200,
        "browser_access": True,
        "catalog_found": True,
        "robots": "404; política não publicada",
        "classification_available": False,
        "observed_items": 78,
        "valid_motorcycles": 0,
        "excluded_by_type": 0,
        "unknown_items": 78,
        "classification_failures": None,
        "diagnostic_errors": 0,
        "metric_scope": "Amostra de diagnóstico, sem publicação no estoque",
        "fields": ["ID", "URL", "fabricante/modelo", "versão", "ano", "preço", "km", "imagem"],
        "routes": ["/Veiculos", "/Home/ObterMarcasPorTipo/1"],
        "warning_codes": ["CLASSIFICATION_UNAVAILABLE"],
    },
    "motonil": {
        "last_validation": "2026-10-05",
        "validation_result": "DADOS INSUFICIENTES PARA CLASSIFICAÇÃO SEGURA",
        "method": "Diagnóstico HTTP/HTML e navegador; sem collector",
        "safe_category": False,
        "http_status": 200,
        "browser_access": True,
        "catalog_found": True,
        "robots": "200; comentários sem diretivas operacionais",
        "classification_available": False,
        "observed_items": 19,
        "valid_motorcycles": 0,
        "excluded_by_type": 0,
        "unknown_items": 19,
        "classification_failures": None,
        "diagnostic_errors": 0,
        "metric_scope": "Amostra de diagnóstico, sem publicação no estoque",
        "fields": ["ID", "URL", "título", "preço", "imagem", "marca no detalhe", "ano/km em texto"],
        "routes": [
            "/MOTOS",
            "/index.php?route=product/category&path=65&limit=25",
            "/index.php?route=information/sitemap",
        ],
        "warning_codes": ["CLASSIFICATION_UNAVAILABLE"],
    },
    "moto_marques": {
        "last_validation": "2026-10-05",
        "validation_result": "BLOQUEADO POR RESTRIÇÃO DE ACESSO",
        "method": "Inspeção manual; HTTP bloqueado; sem collector",
        "safe_category": False,
        "http_status": 403,
        "browser_access": True,
        "catalog_found": True,
        "robots": "Navegador: User-agent: * / Disallow: /; HTTP simples: 403",
        "classification_available": False,
        "observed_items": None,
        "valid_motorcycles": 0,
        "excluded_by_type": None,
        "unknown_items": None,
        "classification_failures": None,
        "diagnostic_errors": 1,
        "metric_scope": "Acesso restrito; sem censo de itens",
        "fields": ["Links /motos/...-ID.html e títulos visíveis; não auditados para publicação"],
        "routes": ["/multipla", "/multipla/veic_status/Novo", "/multipla/veic_status/Usado"],
        "warning_codes": ["ACCESS_RESTRICTED"],
    },
}
