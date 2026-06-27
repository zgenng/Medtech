from __future__ import annotations

import math

from rapidfuzz import fuzz


LOW_VALUE_TOKENS = {
    "услуга",
    "услуги",
    "медицинский",
    "медицинская",
    "платный",
    "платная",
    "прочий",
    "прочая",
    "другой",
    "другая",
    "уточненный",
    "уточненная",
    "локализация",
    "цель",
    "случай",
    "введение",
    "проведение",
    "выполнение",
    "исследование",
    "процедура",
}


class SemanticScorer:
    def combined_score(self, left: str, right: str, fuzzy_score: float) -> float:
        token_set = fuzz.token_set_ratio(left, right) / 100
        token_sort = fuzz.token_sort_ratio(left, right) / 100
        partial = fuzz.partial_ratio(left, right) / 100
        jaccard = self.token_jaccard(left, right)
        coverage = self.important_token_coverage(left, right)
        char_score = self.char_ngram_cosine(left, right)

        return round(
            fuzzy_score * 0.20
            + token_set * 0.20
            + token_sort * 0.15
            + partial * 0.15
            + jaccard * 0.10
            + coverage * 0.15
            + char_score * 0.05,
            4,
        )

    @staticmethod
    def token_jaccard(left: str, right: str) -> float:
        a = set(left.split())
        b = set(right.split())

        if not a or not b:
            return 0.0

        return len(a & b) / len(a | b)

    @staticmethod
    def important_token_coverage(left: str, right: str) -> float:
        a = {token for token in left.split() if token not in LOW_VALUE_TOKENS}
        b = {token for token in right.split() if token not in LOW_VALUE_TOKENS}

        if not a or not b:
            return 0.0

        common = len(a & b)

        recall = common / len(a)
        precision = common / len(b)

        return (recall + precision) / 2

    @staticmethod
    def char_ngram_cosine(left: str, right: str, n: int = 3) -> float:
        def grams(text: str) -> dict[str, int]:
            text = f" {text} "
            result: dict[str, int] = {}

            for i in range(max(len(text) - n + 1, 0)):
                gram = text[i:i + n]
                result[gram] = result.get(gram, 0) + 1

            return result

        a = grams(left)
        b = grams(right)

        if not a or not b:
            return 0.0

        common = set(a) & set(b)
        dot = sum(a[g] * b[g] for g in common)
        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))

        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0