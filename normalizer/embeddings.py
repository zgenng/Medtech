"""Семантические эмбеддинги (§3 ТЗ).

RapidFuzz не поймёт, что «развёрнутый анализ крови» ≈ «общий анализ крови».
Эмбеддинги справочника считаются один раз и держатся в памяти. Если
sentence-transformers не установлен — индекс просто неактивен (available=False),
и каскад работает без семантической ступени.
"""
from __future__ import annotations

import numpy as np


class EmbeddingIndex:
    """Ленивая обёртка над sentence-transformers с косинусной близостью."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None
        self._matrix: np.ndarray | None = None
        self.available = False
        try:  # pragma: no cover - зависит от окружения
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(model_name)
            self.available = True
        except Exception:
            self._model = None
            self.available = False

    def _encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(  # type: ignore[union-attr]
            texts, convert_to_numpy=True, normalize_embeddings=True
        )
        return np.asarray(vectors, dtype=np.float32)

    def build(self, texts: list[str]) -> None:
        """Предпосчитать матрицу эмбеддингов справочника."""
        if not self.available:
            return
        self._matrix = self._encode(texts) if texts else None

    def similarities(self, query: str) -> np.ndarray | None:
        """Косинусная близость запроса ко всем записям справочника (0..1)."""
        if not self.available or self._matrix is None:
            return None
        vec = self._encode([query])[0]
        sims = self._matrix @ vec          # обе стороны L2-нормированы → косинус
        return np.clip((sims + 1.0) / 2.0, 0.0, 1.0)  # из [-1,1] в [0,1]
