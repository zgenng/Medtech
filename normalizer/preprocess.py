"""Предобработка текста (§1 ТЗ) — даёт больше прироста, чем выбор модели.

Поверх utils.text.normalize_key: расшифровка аббревиатур, лемматизация,
удаление довесков и стоп-слов, починка гомоглифов. На выходе — каноничная
строка для сравнения и набор признаков-ловушек.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from utils.text import normalize_key

from . import traps as traps_mod

# --- Лемматизатор (pymorphy3 опционален) ----------------------------------
try:  # pragma: no cover - зависит от окружения
    import pymorphy3

    _MORPH = pymorphy3.MorphAnalyzer()
    HAVE_PYMORPHY = True
except Exception:  # ImportError или несовместимость версии Python
    _MORPH = None
    HAVE_PYMORPHY = False

# --- Гомоглифы: латиница → кириллица (только в смешанных токенах) ----------
_HOMOGLYPH = str.maketrans({
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с",
    "x": "х", "y": "у", "k": "к", "m": "м", "t": "т", "h": "н", "b": "ь",
})
_HAS_LATIN = re.compile(r"[a-z]")
_HAS_CYRILLIC = re.compile(r"[а-я]")

# --- Довески (§1): категории, единицы, дозировки, коды, скобки, № --------
_FILLER_PATTERNS = [
    re.compile(r"\([^)]*\)"),                       # скобочные примечания
    re.compile(r"\b\d+\s*(кат|категори\w*)\b"),     # «1 кат.», «2 категории»
    re.compile(r"\b\d+\s*(ед|шт|штук\w*)\b"),       # «1 ед.», «шт»
    re.compile(r"№\s*\d+"),                          # «№ 5»
    re.compile(r"\b\d+\s*(мг|мкг|мл|г|ме|ед/мл)\b"), # дозировки/единицы
    re.compile(r"\bкод\s*[:№]?\s*\w+"),             # коды источника
]
_DIGIT_TAIL = re.compile(r"\b\d{4,}\b")              # длинные числовые коды

# Лёгкий стеммер-фолбэк, когда pymorphy3 недоступен.
_FALLBACK_SUFFIXES = (
    "ого", "его", "ому", "ему", "ыми", "ими", "ая", "яя", "ое", "ее",
    "ой", "ый", "ий", "ом", "ем", "ах", "ях", "ам", "ям", "ов", "ев",
    "ы", "и", "а", "я", "у", "ю", "е", "о",
)


@dataclass(slots=True)
class PreprocessResult:
    """Результат предобработки одной строки."""

    normalized_name: str           # каноничная форма без расшифровки аббревиатур
    expanded_name: str             # та же форма, но с расшифрованными аббревиатурами
    traps: dict[str, str] = field(default_factory=dict)
    abbrev_applied: bool = False

    @property
    def tokens(self) -> list[str]:
        return self.normalized_name.split()


@lru_cache(maxsize=1)
def load_abbreviations(path_str: str) -> dict[str, str]:
    path = Path(path_str)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {normalize_key(k): str(v) for k, v in data.items() if not k.startswith("_")}


@lru_cache(maxsize=1)
def load_stopwords(path_str: str) -> frozenset[str]:
    path = Path(path_str)
    if not path.exists():
        return frozenset()
    data = json.loads(path.read_text(encoding="utf-8"))
    words = data.get("words", []) if isinstance(data, dict) else data
    return frozenset(normalize_key(w) for w in words)


def _fix_homoglyphs(text: str) -> str:
    out = []
    for token in text.split():
        if _HAS_LATIN.search(token) and _HAS_CYRILLIC.search(token):
            token = token.translate(_HOMOGLYPH)
        out.append(token)
    return " ".join(out)


def strip_fillers(text: str) -> str:
    for pattern in _FILLER_PATTERNS:
        text = pattern.sub(" ", text)
    text = _DIGIT_TAIL.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _lemma(word: str) -> str:
    if _MORPH is not None:
        try:
            return _MORPH.parse(word)[0].normal_form
        except Exception:
            return word
    # Фолбэк: срезаем самое длинное знакомое окончание, сохраняя основу >= 4.
    for suffix in _FALLBACK_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _lemmatize(tokens: list[str], enabled: bool) -> list[str]:
    if not enabled:
        return tokens
    return [_lemma(t) for t in tokens]


def _collapse_initials(tokens: list[str], abbr: dict[str, str]) -> list[str]:
    """Склеить «о а к» → «оак», если результат — известная аббревиатура.

    Так дотовые формы (О.А.К., Э.К.Г.) после normalize_key распадаются на
    одиночные буквы — собираем их обратно только при попадании в словарь.
    """
    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        if len(tokens[i]) == 1 and tokens[i].isalpha():
            j = i
            while j < n and len(tokens[j]) == 1 and tokens[j].isalpha():
                j += 1
            run = tokens[i:j]
            joined = "".join(run)
            if len(run) >= 2 and joined in abbr:
                out.append(joined)
            else:
                out.extend(run)
            i = j
        else:
            out.append(tokens[i])
            i += 1
    return out


def _expand(tokens: list[str], abbr: dict[str, str]) -> tuple[list[str], bool]:
    out: list[str] = []
    changed = False
    for token in tokens:
        expansion = abbr.get(token)
        if expansion:
            out.extend(expansion.split())
            changed = True
        else:
            out.append(token)
    return out, changed


def _drop_stopwords(tokens: list[str], stop: frozenset[str]) -> list[str]:
    kept = [t for t in tokens if t not in stop]
    return kept or tokens  # не отдаём пустую строку, если всё оказалось стоп-словами


def preprocess(
    raw: object,
    *,
    abbreviations_path: str,
    stopwords_path: str,
    use_lemmatization: bool = True,
) -> PreprocessResult:
    abbr = load_abbreviations(abbreviations_path)
    stop = load_stopwords(stopwords_path)

    base = _fix_homoglyphs(normalize_key(raw))
    found_traps = traps_mod.extract_traps(base)   # до удаления довесков (категория!)

    stripped = strip_fillers(base)
    tokens = _collapse_initials(stripped.split(), abbr)

    plain = _drop_stopwords(_lemmatize(tokens, use_lemmatization), stop)
    expanded_tokens, changed = _expand(tokens, abbr)
    expanded = _drop_stopwords(_lemmatize(expanded_tokens, use_lemmatization), stop)

    return PreprocessResult(
        normalized_name=" ".join(plain),
        expanded_name=" ".join(expanded),
        traps=found_traps,
        abbrev_applied=changed,
    )
