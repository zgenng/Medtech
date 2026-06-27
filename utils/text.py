from __future__ import annotations

import re
import unicodedata

_SPACES = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^0-9a-zа-яё]+", re.IGNORECASE)


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").replace("\n", " ")
    text = unicodedata.normalize("NFKC", text)
    return _SPACES.sub(" ", text).strip()


def normalize_key(value: object) -> str:
    text = clean_text(value).lower().replace("ё", "е")
    return _NON_WORD.sub(" ", text).strip()


def looks_like_section(text: str) -> bool:
    key = normalize_key(text)
    markers = ("раздел", "подраздел", "блок", "стационар", "прием врача")
    return any(key.startswith(marker) for marker in markers)


def is_noise(text: str) -> bool:
    key = normalize_key(text)
    if not key:
        return True
    bad = ("приложение", "утверждаю", "председатель", "прейскурант", "цены на", "стоимость", "код наименование")
    if any(key.startswith(prefix) for prefix in bad):
        return True
    return bool(re.fullmatch(r"20\d{2}( год| года)?", key))
