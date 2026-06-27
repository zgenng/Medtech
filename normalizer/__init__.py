"""Нормализатор MedArchive (ТЗ 4.3).

Сопоставляет сырое название услуги из прайса с записью справочника `service`.
Публичный API соответствует разделу «Интерфейс» спецификации:

    from normalizer import Normalizer, ServiceRecord, MatchResult

    norm = Normalizer(services)            # services: list[ServiceRecord]
    res = norm.match("ОАК", category=None) # -> MatchResult(service_id, confidence, stage, ...)
    norm.run_over_unmatched(repository)    # Вариант B: пост-обработка price_item

Для удобства есть и модульный хелпер match(), который держит синглтон,
построенный из repository.load_services().
"""
from __future__ import annotations

from .config import NormalizerConfig
from .matcher import MatchResult, Normalizer, ServiceRecord

__all__ = [
    "NormalizerConfig",
    "Normalizer",
    "ServiceRecord",
    "MatchResult",
    "match",
    "build_from_repository",
    "load_services_from_xlsx",
    "reset",
]


def load_services_from_xlsx(path):
    """Загрузить список ServiceRecord из Excel-справочника."""
    from .catalog import load_services_from_xlsx as _loader

    return _loader(path)

_INSTANCE: Normalizer | None = None


def build_from_repository(repository, config: NormalizerConfig | None = None) -> Normalizer:
    """Собрать нормализатор из справочника, отданного бэкендом."""
    records = [
        ServiceRecord(
            service_id=str(row["service_id"]),
            service_name=row["service_name"],
            synonyms=list(row.get("synonyms") or []),
            category=row.get("category"),
        )
        for row in repository.load_services()
    ]
    return Normalizer(records, config)


def match(
    raw_name: str,
    category: str | None = None,
    source_code: str | None = None,
) -> MatchResult:
    """Сопоставить одно название, используя справочник из repository (Вариант A).

    Ленивая инициализация синглтона. Требует репозиторий с load_services();
    если бэкенд недоступен, используйте Normalizer(services).match() напрямую.
    """
    global _INSTANCE
    if _INSTANCE is None:
        import repository  # ленивый импорт: не тянем БД, пока не нужно

        _INSTANCE = build_from_repository(repository)
    return _INSTANCE.match(raw_name, category, source_code)


def reset() -> None:
    """Сбросить синглтон (например, после обновления справочника)."""
    global _INSTANCE
    _INSTANCE = None
