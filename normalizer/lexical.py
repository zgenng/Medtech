"""Лексический fuzzy-скор (ступень 4, §2 ТЗ).

RapidFuzz token_set_ratio устойчив к перестановке слов. Если rapidfuzz не
установлен — используем эквивалент на стандартной библиотеке (difflib +
пересечение множеств токенов), чтобы каскад работал без тяжёлых зависимостей.
"""
from __future__ import annotations

from difflib import SequenceMatcher

try:  # pragma: no cover - зависит от окружения
    from rapidfuzz import fuzz as _rf_fuzz

    HAVE_RAPIDFUZZ = True
except Exception:
    _rf_fuzz = None
    HAVE_RAPIDFUZZ = False


def _fallback_token_set_ratio(a: str, b: str) -> float:
    """Приближение rapidfuzz.token_set_ratio на стандартной библиотеке (0..100)."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    diff_a = " ".join(sorted(ta - tb))
    diff_b = " ".join(sorted(tb - ta))
    base = " ".join(sorted(inter))
    sorted_a = (base + " " + diff_a).strip()
    sorted_b = (base + " " + diff_b).strip()
    ratios = [
        SequenceMatcher(None, base, sorted_a).ratio(),
        SequenceMatcher(None, base, sorted_b).ratio(),
        SequenceMatcher(None, sorted_a, sorted_b).ratio(),
    ]
    return max(ratios) * 100.0


def token_set_ratio(a: str, b: str) -> float:
    """Лексическая близость двух нормализованных строк, 0..1."""
    if not a or not b:
        return 0.0
    if _rf_fuzz is not None:
        return _rf_fuzz.token_set_ratio(a, b) / 100.0
    return _fallback_token_set_ratio(a, b) / 100.0
