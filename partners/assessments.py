"""Assessment metadata is informational; never registers executable collectors."""

CANDIDATES = (
    {
        "partner": "moto_marques",
        "display_name": "Moto Marques Multimarcas",
        "url": "https://motomarquesmultimarcas.com.br/",
        "reason": "Restrição técnica de acesso (HTTP 403).",
    },
    {
        "partner": "thomas_motos",
        "display_name": "Thomas Motos",
        "url": "https://thomasmotos.com.br/Veiculos",
        "reason": "Estoque misto sem classificação verificável de motocicletas.",
    },
    {
        "partner": "motonil",
        "display_name": "Motonil",
        "url": "https://www.motonil.com.br/MOTOS",
        "reason": "Categoria inclui kart e serviço; tipo e identidade sem estrutura uniforme verificada.",
    },
)


def unintegrated(registry):
    configured = {p.partner_key for p in registry.list()}
    return [
        {**p, "integration_status": "Não integrado", "enabled": False}
        for p in CANDIDATES
        if p["partner"] not in configured
    ]
