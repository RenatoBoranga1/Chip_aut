from collections import defaultdict

from matching.fuzzy_matcher import combined_model, compare_features, features
from matching.models import Candidate, MatchResult, MotorcycleQuery
from matching.rules import MatchingRules
from scanner_base.models import Motorcycle
from scanner_base.normalizer import normalize_manufacturer, normalize_model, normalize_year, normalized_key


class Matcher:
    def __init__(
        self, motorcycles: list[Motorcycle], aliases: dict[str, str], rules: MatchingRules, memory: dict | None = None
    ):
        if not motorcycles:
            raise ValueError("Base vazia: importe a planilha antes de comparar")
        self.rules = rules
        self.aliases = aliases
        self.memory = memory or {}
        self.exact = {}
        self.groups = defaultdict(list)
        for motorcycle in motorcycles:
            if motorcycle.key in self.exact:
                raise ValueError(f"Identidade duplicada na base de matching: {motorcycle.key}")
            self.exact[motorcycle.key] = motorcycle
            self.groups[motorcycle.manufacturer, motorcycle.year].append(
                (motorcycle, features(motorcycle.model, motorcycle.manufacturer))
            )

    def match(self, query: MotorcycleQuery) -> MatchResult:
        try:
            if not isinstance(query.manufacturer, str) or not query.manufacturer.strip():
                raise ValueError("Montadora obrigatória")
            if not isinstance(query.model, str) or not normalize_model(query.model):
                raise ValueError("Modelo obrigatório")
            if not isinstance(query.version, str):
                raise ValueError("Versão deve ser texto")
            manufacturer = normalize_manufacturer(query.manufacturer, self.aliases)
            if not any(c.isalnum() for c in manufacturer):
                raise ValueError("Montadora sem letras ou números identificáveis")
            model = combined_model(query.model, query.version)
            if not any(t.isalnum() for t in features(model).tokens):
                raise ValueError("Modelo sem letras ou números identificáveis")
            year = normalize_year(query.year)
            key = normalized_key(manufacturer, model, year)
        except ValueError as exc:
            return MatchResult(query, None, "REVISAR", 0.0, None, None, True, [str(exc)], [])
        decisions = self.memory.get(key, {})
        rejected = {k for k, v in decisions.items() if v == "REJEITAR"}
        confirmed = [self.exact[k] for k, v in decisions.items() if v == "CONFIRMAR" and k in self.exact]
        if len(confirmed) == 1:
            m = confirmed[0]
            candidate = Candidate(
                m.key,
                m.manufacturer,
                m.model,
                m.year,
                m.status,
                None,
                ["Confirmação humana persistente consultada antes do fuzzy"],
            )
            return MatchResult(
                query, key, "CONFIRMADO_MANUALMENTE", None, m.key, m.status, False, candidate.reasons, [candidate], 1
            )
        if len(confirmed) > 1:
            choices = [
                Candidate(
                    m.key, m.manufacturer, m.model, m.year, m.status, None, ["Confirmação persistente conflitante"]
                )
                for m in confirmed
            ]
            return MatchResult(
                query,
                key,
                "AMBIGUOUS",
                None,
                None,
                None,
                True,
                ["Mais de uma confirmação persistente; revisar regras"],
                choices,
                len(choices),
            )
        query_features = features(model, manufacturer)
        if (motorcycle := self.exact.get(key)) and key not in rejected:
            candidate = Candidate(
                motorcycle.key,
                motorcycle.manufacturer,
                motorcycle.model,
                motorcycle.year,
                motorcycle.status,
                100.0,
                ["Igualdade da chave normalizada"],
            )
            # A catalog name may omit the trim even when a base-model key exists.
            extensions = []
            for other, target in self.groups.get((manufacturer, year), []):
                if (
                    other.key not in rejected
                    and other.key != key
                    and len(target.tokens) > len(query_features.tokens)
                    and target.tokens[: len(query_features.tokens)] == query_features.tokens
                ):
                    extension = compare_features(query_features, other, target, self.rules, True)
                    if extension:
                        extensions.append(extension)
            if extensions and not query.version.strip():
                extensions.sort(key=lambda c: (-c.confidence, c.scanner_key))
                return MatchResult(
                    query,
                    key,
                    "AMBIGUOUS",
                    100.0,
                    None,
                    None,
                    True,
                    [
                        "Nome coincide com modelo base, mas pode omitir versão; "
                        "existem variantes mais específicas no mesmo ano"
                    ],
                    [candidate, *extensions][: max(2, self.rules.max_candidates)],
                    1 + len(extensions),
                )
            return MatchResult(
                query,
                key,
                "EXATO_NORMALIZADO",
                100.0,
                motorcycle.key,
                motorcycle.status,
                False,
                candidate.reasons,
                [candidate],
                1,
            )
        candidates = []
        for motorcycle, target in self.groups.get((manufacturer, year), []):
            if motorcycle.key in rejected:
                continue
            candidate = compare_features(query_features, motorcycle, target, self.rules)
            if candidate:
                candidates.append(candidate)
        candidates.sort(key=lambda c: (-c.confidence, c.scanner_key))
        if not candidates:
            return MatchResult(
                query,
                key,
                "NAO_ENCONTRADA_NA_BASE",
                0.0,
                None,
                "NAO_ENCONTRADA_NA_BASE",
                False,
                [
                    "Nenhum candidato passou os filtros de montadora/ano/números e o limiar mínimo; "
                    "isso não é prova de inexistência nem confiança de 100%."
                ],
                [],
            )
        first = candidates[0]
        # Evaluate ambiguity BEFORE truncating the visible candidate list.
        ambiguous = len(candidates) > 1 and first.confidence - candidates[1].confidence < self.rules.ambiguity_margin
        probable = first.confidence >= self.rules.probable_threshold and not first.blockers and not ambiguous
        reasons = ["Correspondência aproximada exige confirmação humana"]
        if ambiguous:
            reasons.append("Candidatos próximos: diferença abaixo da margem de ambiguidade")
        if first.blockers:
            reasons.extend(first.blockers)
        if first.confidence < self.rules.probable_threshold:
            reasons.append("Pontuação abaixo do limiar de correspondência provável")
        return MatchResult(
            query,
            key,
            "CORRESPONDENCIA_PROVAVEL" if probable else "REVISAR",
            first.confidence,
            None,
            None,
            True,
            reasons,
            candidates[: self.rules.max_candidates],
            len(candidates),
        )

    def match_many(self, queries):
        """Reuse in-memory indexes and manual decisions; no SQL in this loop."""
        return [self.match(query) for query in queries]
