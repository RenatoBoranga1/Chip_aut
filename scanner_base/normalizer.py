"""Conservative identity normalization; no fuzzy equivalence in milestone 1."""

import re
import unicodedata


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value))
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).upper().split())


def normalize_model(value: str) -> str:
    # Preserve punctuation that can denote a version (R+, 125/150, etc.).
    return re.sub(r"[\s\-‐‑‒–—]", "", normalize_text(value))


def normalize_manufacturer(value: str, aliases: dict[str, str]) -> str:
    value = normalize_text(value)
    return aliases.get(value, value)


def normalize_year(value: str) -> int:
    if not re.fullmatch(r"\d{4}(?:\.0+)?", str(value).strip()):
        raise ValueError(f"Ano inválido ou ambíguo: {value!r}")
    year = int(float(value))
    if not 1885 <= year <= 2100:
        raise ValueError(f"Ano fora da faixa 1885–2100: {year}")
    return year


def normalized_key(manufacturer: str, model: str, year: int) -> str:
    if "|" in manufacturer or "|" in model:
        raise ValueError("Identidade contém separador reservado '|'")
    return f"{manufacturer}|{normalize_model(model)}|{year}"
