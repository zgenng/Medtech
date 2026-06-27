from __future__ import annotations

from rapidfuzz import fuzz, process


class LexicalMatcher:
    def top_candidates(
        self,
        query: str,
        choices: list[str],
        limit: int = 30,
    ) -> list[tuple[str, float]]:
        scores: dict[str, float] = {}

        scorers = [
            fuzz.WRatio,
            fuzz.token_set_ratio,
            fuzz.token_sort_ratio,
            fuzz.partial_ratio,
        ]

        for scorer in scorers:
            found = process.extract(
                query,
                choices,
                scorer=scorer,
                limit=limit,
            )

            for text, score, _ in found:
                value = score / 100
                scores[text] = max(scores.get(text, 0.0), value)

        return sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]