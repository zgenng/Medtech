"""Доменные ловушки (§6 ТЗ): признаки, которые делают услуги разными.

Если у «сырого» названия и кандидата эти признаки заданы и не совпадают
(правый vs левый, с контрастом vs без), матч штрафуется — иначе анализ крови
улетит в анализ мочи, а МРТ с контрастом — в МРТ без.
"""
from __future__ import annotations

import re

# feature -> {значение: regex по нормализованному тексту}
_TRAP_RULES: dict[str, dict[str, re.Pattern[str]]] = {
    "side": {
        "left": re.compile(r"\bлев(ый|ая|ое|ого|ой|ом|осторонн\w*)\b"),
        "right": re.compile(r"\bправ(ый|ая|ое|ого|ой|ом|осторонн\w*)\b"),
    },
    "contrast": {
        "with": re.compile(r"\bс\s+контраст\w*"),
        "without": re.compile(r"\bбез\s+контраст\w*"),
    },
    "trimester": {
        "1": re.compile(r"\b(1|i|перв\w+)\s+триместр"),
        "2": re.compile(r"\b(2|ii|втор\w+)\s+триместр"),
        "3": re.compile(r"\b(3|iii|трет\w+)\s+триместр"),
    },
    "visit": {
        "primary": re.compile(r"\bпервичн\w+"),
        "repeat": re.compile(r"\bповторн\w+"),
    },
    "age": {
        "adult": re.compile(r"\bвзросл\w+"),
        "child": re.compile(r"\b(детск\w+|ребен\w+|ребён\w+|педиатр\w*)"),
    },
    "category": {
        "1": re.compile(r"\b1\s*(кат|категори\w*)"),
        "2": re.compile(r"\b2\s*(кат|категори\w*)"),
        "3": re.compile(r"\b3\s*(кат|категори\w*)"),
    },
}


def extract_traps(text: str) -> dict[str, str]:
    """Вернуть найденные признаки-ловушки нормализованного текста."""
    found: dict[str, str] = {}
    for feature, values in _TRAP_RULES.items():
        for value, pattern in values.items():
            if pattern.search(text):
                found[feature] = value
                break
    return found


def has_conflict(raw_traps: dict[str, str], cand_traps: dict[str, str]) -> bool:
    """True, если хоть один признак задан с обеих сторон и значения расходятся."""
    for feature, raw_value in raw_traps.items():
        cand_value = cand_traps.get(feature)
        if cand_value is not None and cand_value != raw_value:
            return True
    return False
