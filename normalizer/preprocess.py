from __future__ import annotations

import re

import pymorphy3


_WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)

NOISE_WORDS = {
    "усл", "услуга", "услуги",
    "глаз", "глаза",
    "левый", "левая", "левое", "левого",
    "правый", "правая", "правое", "правого",
    "первичный", "первичная", "первичное",
    "повторный", "повторная", "повторное",
    "однократно", "двукратно",
}

TYPO_REPLACEMENTS = {
    "иньекция": "инъекция",
    "коньюктива": "конъюнктива",
    "коньюктиву": "конъюнктива",
    "коньюнктива": "конъюнктива",
    "бронхоскопия": "бронхоскопия",
}

ABBREVIATIONS = {
    "оак": "общий анализ крови",
    "оам": "общий анализ мочи",
    "экг": "электрокардиография",
    "узи": "ультразвуковое исследование",
    "мрт": "магнитно резонансная томография",
    "кт": "компьютерная томография",
    "бца": "брахиоцефальные артерии",
    "фгдс": "фиброгастродуоденоскопия",
    "фкс": "фиброколоноскопия",
    "трузи": "трансректальное ультразвуковое исследование",
    "рча": "радиочастотная абляция",
    "хм": "холтеровское мониторирование",
    "чсс": "частота сердечных сокращений",
    "чдд": "частота дыхательных движений",
}

MEDICAL_REPLACEMENTS = {
    "консультация": "прием",
    "консультативный": "прием",
    "конс": "прием",
    "приём": "прием",
    "врач": "",
    "врача": "",
    "доктор": "",
    "доктора": "",
    "специалист": "",
    "специалиста": "",
    "рентгенография": "рентген",
    "рентгенограмма": "рентген",
    "ультразвук": "ультразвуковое исследование",
}


class TextPreprocessor:
    def __init__(self):
        self.morph = pymorphy3.MorphAnalyzer()

    def normalize(self, text: object) -> str:
        text = "" if text is None else str(text)
        text = text.lower().replace("ё", "е")

        text = self._remove_brackets(text)
        text = self._clean_symbols(text)
        text = self._replace_words(text, TYPO_REPLACEMENTS)
        text = self._replace_words(text, ABBREVIATIONS)
        text = self._replace_words(text, MEDICAL_REPLACEMENTS)

        tokens = _WORD_RE.findall(text)
        tokens = [self._lemmatize(token) for token in tokens]
        tokens = [token for token in tokens if self._keep_token(token)]

        return " ".join(tokens)

    def tokens(self, text: object) -> set[str]:
        return set(self.normalize(text).split())

    @staticmethod
    def _remove_brackets(text: str) -> str:
        text = re.sub(r"\([^)]*\)", " ", text)
        text = re.sub(r"\d+\s*(усл|услуга|глаз|глаза)", " ", text)
        return text

    @staticmethod
    def _clean_symbols(text: str) -> str:
        text = text.replace("№", " ")
        text = re.sub(r"[,.;:|/\\_\-+*]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _replace_words(text: str, mapping: dict[str, str]) -> str:
        result = text
        for old, new in mapping.items():
            result = re.sub(rf"\b{re.escape(old)}\b", f" {new} ", result)
        return re.sub(r"\s+", " ", result).strip()

    def _lemmatize(self, token: str) -> str:
        if token.isdigit():
            return token
        parsed = self.morph.parse(token)
        return parsed[0].normal_form if parsed else token

    @staticmethod
    def _keep_token(token: str) -> bool:
        if not token:
            return False
        if token.isdigit():
            return False
        if len(token) <= 1:
            return False
        if token in NOISE_WORDS:
            return False
        return True