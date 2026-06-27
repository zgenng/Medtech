from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ServiceRecord:
    service_id: str
    service_name: str
    category: str | None = None
    code: str | None = None
    tarificator_code: str | None = None
    synonyms: list[str] = field(default_factory=list)
    normalized_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MatchResult:
    service_id: str | None
    service_name: str | None
    category: str | None
    score: float
    status: str
    method: str
    reason: str


@dataclass(slots=True)
class NormalizedItem:
    original: Any
    service_id: str | None
    service_name: str | None
    category: str | None
    score: float
    status: str
    method: str
    verification_note: str


@dataclass(slots=True)
class NormalizationReport:
    total: int = 0
    auto_matched: int = 0
    needs_review: int = 0
    unmatched: int = 0

    @property
    def auto_rate(self) -> float:
        return round(self.auto_matched / self.total * 100, 2) if self.total else 0.0