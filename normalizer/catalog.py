"""Загрузка справочника услуг из Excel (портировано из версии коллеги).

Гибко подбирает колонки по нескольким возможным заголовкам и генерит
стабильный service_id через uuid5, если его нет в файле. Читаем через
openpyxl (уже в зависимостях парсера) — pandas не требуется.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from .matcher import ServiceRecord

# Кандидаты заголовков (в нижнем регистре) для каждого поля.
_NAME = ["service_name", "name_ru", "name", "название", "услуга", "наименование"]
_CATEGORY = ["category", "специальность", "категория"]
_CODE = ["code", "service_code", "код"]
_TARIF = ["tarificatrcode", "tarificator_code", "тарификатор"]
_ID = ["service_id", "uuid", "id"]
_SYN = ["synonyms", "синонимы", "aliases"]


def load_services_from_xlsx(path: str | Path) -> list[ServiceRecord]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        try:
            header = next(rows)
        except StopIteration:
            return []

        index: dict[str, int] = {}
        for i, cell in enumerate(header):
            if cell is not None:
                index[str(cell).strip().lower()] = i

        def pick(row: tuple, names: list[str]) -> str | None:
            for name in names:
                i = index.get(name)
                if i is not None and i < len(row) and row[i] not in (None, ""):
                    value = str(row[i]).strip()
                    if value:
                        return value
            return None

        services: list[ServiceRecord] = []
        for row in rows:
            if row is None:
                continue
            name = pick(row, _NAME)
            if not name:
                continue
            code = pick(row, _CODE)
            tarif = pick(row, _TARIF)
            raw_id = pick(row, _ID)
            service_id = raw_id or str(
                uuid.uuid5(uuid.NAMESPACE_DNS, f"{name}|{code}|{tarif}")
            )
            services.append(
                ServiceRecord(
                    service_id=str(service_id),
                    service_name=name,
                    synonyms=_parse_synonyms(pick(row, _SYN)),
                    category=pick(row, _CATEGORY),
                    code=code,
                    tarificator_code=tarif,
                )
            )
        return services
    finally:
        wb.close()


def _parse_synonyms(value: str | None) -> list[str]:
    if not value:
        return []
    value = value.strip().strip("[]")
    parts = re.split(r"[;,\n|]+", value)
    return [p.strip().strip('"').strip("'") for p in parts if p.strip()]
