from __future__ import annotations

from typing import Iterable

from normalizer.catalog import ServiceCatalog
from normalizer.lexical import LexicalMatcher
from normalizer.models import MatchResult, NormalizationReport, NormalizedItem, ServiceRecord
from normalizer.semantic import SemanticScorer


class ServiceMatcher:
    def __init__(
        self,
        catalog: ServiceCatalog,
        auto_threshold: float = 0.78,
        review_threshold: float = 0.55,
    ):
        self.catalog = catalog
        self.lexical = LexicalMatcher()
        self.semantic = SemanticScorer()
        self.auto_threshold = auto_threshold
        self.review_threshold = review_threshold

    def match(self, raw_name: str, source_code: str | None = None) -> MatchResult:
        normalized = self.catalog.normalize_name(raw_name)

        if not normalized:
            return self._empty("empty_name")

        code_match = self._match_by_code(source_code)
        if code_match:
            return self._result(code_match, 0.98, "auto", "code", "matched by source code")

        exact_match = self.catalog.by_exact.get(normalized)
        if exact_match:
            return self._result(exact_match, 1.0, "auto", "exact", "exact normalized name")

        candidates = self.lexical.top_candidates(
            normalized,
            self.catalog.choices,
            limit=30,
        )

        if not candidates:
            return self._empty("no_candidates")

        best_service = None
        best_score = 0.0

        for candidate_text, fuzzy_score in candidates:
            service = self.catalog.choice_to_service[candidate_text]
            score = self.semantic.combined_score(normalized, candidate_text, fuzzy_score)

            if score > best_score:
                best_score = score
                best_service = service

        if best_service is None:
            return self._empty("no_best_candidate")

        if best_score >= self.auto_threshold:
            return self._result(
                best_service,
                best_score,
                "auto",
                "fuzzy_semantic",
                f"score={best_score:.3f}",
            )

        if best_score >= self.review_threshold:
            return self._result(
                best_service,
                best_score,
                "needs_review",
                "fuzzy_semantic",
                f"score={best_score:.3f}",
            )

        return MatchResult(
            service_id=None,
            service_name=None,
            category=None,
            score=round(best_score, 4),
            status="unmatched",
            method="fuzzy_semantic",
            reason=f"best candidate: {best_service.service_name}; score={best_score:.3f}",
        )

    def normalize_items(self, items: Iterable[object]) -> tuple[list[NormalizedItem], NormalizationReport]:
        normalized_items: list[NormalizedItem] = []
        report = NormalizationReport()

        for item in items:
            report.total += 1

            raw_name = getattr(item, "service_name_raw", "")
            source_code = getattr(item, "service_code_source", None)

            match = self.match(raw_name, source_code)

            normalized_items.append(
                NormalizedItem(
                    original=item,
                    service_id=match.service_id,
                    service_name=match.service_name,
                    category=match.category,
                    score=match.score,
                    status=match.status,
                    method=match.method,
                    verification_note=f"{match.status}: {match.service_name}; {match.reason}",
                )
            )

            if match.status == "auto":
                report.auto_matched += 1
            elif match.status == "needs_review":
                report.needs_review += 1
            else:
                report.unmatched += 1

        return normalized_items, report

    def _match_by_code(self, source_code: str | None) -> ServiceRecord | None:
        if not source_code:
            return None
        return self.catalog.by_code.get(str(source_code).strip().lower())

    def _result(
        self,
        service: ServiceRecord,
        score: float,
        status: str,
        method: str,
        reason: str,
    ) -> MatchResult:
        return MatchResult(
            service_id=service.service_id,
            service_name=service.service_name,
            category=service.category,
            score=round(score, 4),
            status=status,
            method=method,
            reason=reason,
        )

    @staticmethod
    def _empty(reason: str) -> MatchResult:
        return MatchResult(
            service_id=None,
            service_name=None,
            category=None,
            score=0.0,
            status="unmatched",
            method="none",
            reason=reason,
        )