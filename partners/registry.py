from partners.wr_motos import WRMotosCollector

COLLECTORS = {"wr_motos": WRMotosCollector}


def create_collector(name, **kwargs):
    if name not in COLLECTORS:
        raise ValueError(f"Parceiro desconhecido: {name}")
    return COLLECTORS[name](**kwargs)
