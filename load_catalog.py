"""Загрузка целевого справочника услуг в БД (ТЗ 2.2).

Читает xlsx/json-справочник организаторов и апсертит услуги в таблицу service,
к которой нормализатор привязывает извлечённые позиции прайсов.

Использование:
    python load_catalog.py "Справочник услуг.xlsx"
    python load_catalog.py path/to/catalog.xlsx --dry-run   # только показать, не писать

Колонки определяются гибко (см. normalizer/catalog.py): Name_ru/название,
Специальность/категория, Code, TarificatrCode, synonyms.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from normalizer.catalog import load_services_from_xlsx


def main() -> None:
    parser = argparse.ArgumentParser(description="Загрузить справочник услуг в БД")
    parser.add_argument("catalog", help="Путь к xlsx-справочнику услуг")
    parser.add_argument("--dry-run", action="store_true", help="Не писать в БД, только разобрать и показать сводку")
    args = parser.parse_args()

    path = Path(args.catalog)
    if not path.exists():
        sys.exit(f"Файл не найден: {path}")

    records = load_services_from_xlsx(path)
    if not records:
        sys.exit("В справочнике не найдено ни одной услуги (проверьте колонку с названием).")

    specialties = sorted({r.category for r in records if r.category})
    names = {r.service_name for r in records}
    print(f"Разобрано записей: {len(records)}")
    print(f"Уникальных названий услуг: {len(names)}")
    print(f"Специальностей: {len(specialties)}")
    print("Примеры:")
    for r in records[:5]:
        print(f"  · [{r.category}] {r.service_name}  (code={r.code}, tarif={r.tarificator_code})")

    if args.dry_run:
        print("\n--dry-run: в БД ничего не записано.")
        return

    import repository

    result = repository.upsert_services(records)
    print(
        f"\nГотово. В БД: получено {result['received']}, "
        f"добавлено {result['inserted']}, обновлено {result['updated']}."
    )


if __name__ == "__main__":
    main()
