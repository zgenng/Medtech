"""Настройки нормализатора. Пороги и веса калибруются на gold-наборе (eval/)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(slots=True)
class NormalizerConfig:
    """Пороги, веса гибрида и пути к словарям.

    Два порога (см. §4 ТЗ):
      score >= auto_threshold      → автосопоставление;
      score <= unmatched_threshold → service_id = NULL (очередь /unmatched);
      между                        → очередь ручной верификации.
    """

    # Пороги (0..1)
    auto_threshold: float = _env_float("NORM_AUTO_THRESHOLD", 0.90)
    unmatched_threshold: float = _env_float("NORM_UNMATCHED_THRESHOLD", 0.70)

    # Веса гибридного скора: lexical_weight + semantic_weight == 1.0
    lexical_weight: float = _env_float("NORM_LEXICAL_WEIGHT", 0.5)
    semantic_weight: float = _env_float("NORM_SEMANTIC_WEIGHT", 0.5)

    # Фиксированные скоры ранних (точных) ступеней каскада
    code_score: float = 0.99      # совпадение по коду услуги из источника
    exact_score: float = 1.0
    synonym_score: float = 0.98
    abbrev_score: float = 0.95

    # Доменные ловушки: множитель к скору при конфликте признаков
    # (правый/левый, с контрастом/без, триместр, первичный/повторный, взрослый/детский)
    trap_penalty: float = _env_float("NORM_TRAP_PENALTY", 0.55)

    # Сужение кандидатов (blocking) — сколько лучших по лексике переранжировать эмбеддингами
    max_candidates: int = 50

    # Семантическая модель (см. §3). LaBSE лучше для русского+казахского.
    embedding_model: str = os.getenv("NORM_EMBEDDING_MODEL", "sentence-transformers/LaBSE")

    # Переключатели ступеней; автоматически гаснут, если зависимость не установлена.
    use_lemmatization: bool = True
    use_fuzzy: bool = True
    use_embeddings: bool = True

    # Пути к пополняемым словарям
    abbreviations_path: Path = _HERE / "abbreviations.json"
    stopwords_path: Path = _HERE / "stopwords.json"

    def validate(self) -> "NormalizerConfig":
        if not (0.0 <= self.unmatched_threshold <= self.auto_threshold <= 1.0):
            raise ValueError(
                "Должно выполняться 0 <= unmatched_threshold <= auto_threshold <= 1"
            )
        total = self.lexical_weight + self.semantic_weight
        if abs(total - 1.0) > 1e-6:
            raise ValueError("lexical_weight + semantic_weight должно равняться 1.0")
        return self
