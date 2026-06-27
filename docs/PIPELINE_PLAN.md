# План сборки пайплайна — MedArchive

Цель: замкнуть сквозной поток
**архив → парсер → валидация → нормализатор → Supabase → API/поиск**.

Готово на старте: парсер (`ArchiveParser.parse()` → payload), нормализатор
(`Normalizer`, `run_over_unmatched`), схема БД в Supabase, read-слой
`repository.py` (`load_services`, `iter_unmatched`, `update_match`).
Недостающие звенья выделены ниже.

Целевой поток:
```
ZIP/папка ─► ArchiveParser ─► validate ─► Repository.save() ─► Supabase
                                              │
                                   run_over_unmatched() ─► UPDATE service_id
                                              │
                                          FastAPI ─► /search /services /unmatched /match
```

---

## Этап 0. Согласовать модель со схемой (предусловие)
Без этого загрузчик соберёт неверный payload.

- В `models.PriceItem` добавить `service_id`, `match_confidence`.
- `source_row`/`source_sheet` исключить из payload вставки (служебные).
- В `PriceDocument` согласовать `file_path`, `created_at` с таблицей.

**Готово, когда:** ключи `to_plain_dict(item)` ⊆ колонок таблицы `price_item`.

---

## Этап 1. Загрузчик в Supabase (write-слой repository.py)  ← начинаем
Добавить к существующему read-слою функции записи.

- `upsert_partner(partner) -> partner_id` — дедуп по `bin`, иначе `name`+`city`.
- `insert_document(document) -> doc_id`.
- `bulk_insert_items(items)` — пакетно (`executemany`/`COPY`), с учётом `uq_item_dedup`,
  `ON CONFLICT DO NOTHING` или версионирование (передаётся команде 4.4).
- `save(payload)` — транзакция на документ: партнёр → документ → позиции;
  ошибка → откат, документу статус `error`.
- Идемпотентность: повторная загрузка того же файла не плодит дубли.

**Готово, когда:** после прогона в Supabase появляются строки во всех трёх таблицах,
повторный прогон не дублирует.

---

## Этап 2. Оркестрация parse → normalize → load
Связать три готовых куска. Рекомендуемый порядок — **load-then-match** (Вариант B),
он переиспользует готовый `run_over_unmatched` и опирается на дедуп в БД.

- `pipeline.py`:
  1. `payload = ArchiveParser(config).parse(source)`
  2. `Repository.save(payload)` — позиции ложатся с `service_id = NULL`
  3. `norm = build_from_repository(repository)`
  4. `stats = norm.run_over_unmatched(repository, write=True)`
  5. вернуть сводный отчёт (parse-report + normalize-stats)
- Альтернатива (Вариант A, инлайн): звать `normalizer.match()` до вставки —
  быстрее, но сложнее в транзакции; оставить как оптимизацию.

**Готово, когда:** одна команда проводит файл от архива до проставленных `service_id`.

---

## Этап 3. CLI / точка запуска
- В `cli.py` флаг `--to-db` (писать в Supabase) и `--normalize` (запускать ступень 4).
- Без флагов — текущее поведение (JSON/CSV), чтобы ничего не сломать.
- Лог: сколько документов, позиций, % автосопоставления, ошибки.

**Готово, когда:** `python cli.py --archive x.zip --to-db --normalize` отрабатывает целиком.

---

## Этап 4. REST API (FastAPI)
- `main.py`: зависимость БД из `db.get_cursor`, эндпоинты —
  `GET /services`, `/services/{id}/partners`, `/partners`, `/partners/{id}/services`,
  `GET /search?q=` (pg_trgm, индексы есть), `GET /unmatched`, `POST /match`,
  `POST /items`, `GET /stats`, `GET /health`.
- Pydantic-схемы ответов с `service_id`/`match_confidence`; Swagger на `/docs`.

**Готово, когда:** поиск и выборки возвращают данные из Supabase, Swagger открывается.

---

## Этап 5. Сквозной тест и отчёт качества
- Smoke-тест пайплайна на эталонном мини-архиве (по 1 файлу каждого формата:
  PDF-текст, PDF-скан, XLSX, DOCX) → проверить число строк в БД и `service_id`.
- Проверка идемпотентности: повторный прогон не меняет счётчики.
- Отчёт: документы, % автонормализации, размеры очередей `unmatched`/`needs_review`.
- Нефункциональные: текстовый документ < 60 c, скан < 3 мин.

**Готово, когда:** есть воспроизводимый прогон с метриками и зелёный smoke-тест.

---

## Зависимости (поставить на машине разработки)
```
psycopg[binary,pool], python-dotenv      # БД (уже стоят)
rapidfuzz, sentence-transformers, pymorphy3   # полная сила нормализатора (LaBSE)
openpyxl, python-docx, pdfplumber, PyMuPDF, pytesseract, Pillow  # парсеры
fastapi, uvicorn                          # API (этап 4)
```
> Без `sentence-transformers` нормализатор падает на difflib и теряет семантику
> (кейс «развёрнутый анализ крови» → «общий анализ крови» не ловится).

## Граница ответственности
Этапы 1–4 — мой бэкенд. Версионирование/аномалии в `bulk_insert_items` (ТЗ 4.4),
импорт справочника и `/stats`-запрос (ТЗ 4.5/4.6) — команда (см. BACKEND_PLAN.md).

## Приоритет
0 → 1 (загрузчик) → 2 (оркестрация) → 3 (CLI) → 4 (API) → 5 (тест/отчёт).
