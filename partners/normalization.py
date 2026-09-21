"""Identity enrichment, deliberately separate from transport and HTML parsing."""

from scanner_base.normalizer import normalize_manufacturer, normalized_key


def normalize_advertisement(ad, aliases):
    if ad.manufacturer and ad.model and ad.year:
        try:
            ad.normalized_key = normalized_key(normalize_manufacturer(ad.manufacturer, aliases), ad.model, ad.year)
        except ValueError:
            ad.parse_warnings.append("IDENTIDADE_INVALIDA")
    return ad
