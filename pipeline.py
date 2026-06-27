"""Оркестрация сквозного потока (Этап 2 PIPELINE_PLAN): parse → load → normalize.

Вариант B (load-then-match): позиции сначала ложатся в БД с service_id=NULL,
затем нормализатор проходит по очереди unmatched и проставляет service_id.
Переиспользует готовые run_over_unmatched() и дедуп в БД.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from archive_parser import ArchiveParser
from config import ParserConfig


def run(
    source: str | Path,
    *,
    config: ParserConfig | None = None,
    to_db: bool = False,
    normalize: bool = False,
) -> dict[str, Any]:
    """Провести один источник (ZIP/папка/файл) через пайплайн.

    Без to_db — только парсинг (отчёт). С to_db — запись в Supabase. Дополнительно
    с normalize — прогон нормализатора по очереди unmatched. Возвращает сводку.
    """
    config = config or ParserConfig()
    payload = ArchiveParser(config).parse(source)
    summary: dict[str, Any] = {"parse_report": payload["report"], "payload": payload}

    if not to_db:
        return summary

    import repository  # ленивый импорт: БД нужна только в режиме --to-db

    summary["save_report"] = repository.save(payload)

    if normalize:
        from normalizer import build_from_repository

        norm = build_from_repository(repository)
        summary["normalize_stats"] = norm.run_over_unmatched(repository, write=True)

    return summary
