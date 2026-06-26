# MedArchive — ядро (backend + БД)

Обработка архива прайсов клиник-партнёров: услуги, цены, поиск.
Это **ядро**, на которое опираются парсеры, нормализатор и фронт.

## Стек
- PostgreSQL (локально — Postgres.app, порт **5433**, база `arman`)
- FastAPI + psycopg 3
- OpenAPI/Swagger — генерируется автоматически на `/docs`

## Структура
```
schema.sql        — 4 таблицы (service, partner, price_document, price_item) + enum + индексы
seed.sql          — тестовые данные, чтобы проверить API до готовых парсеров
db.py             — пул подключений к Postgres
models.py         — Pydantic-схемы = контракт между сервисами
main.py           — FastAPI-приложение и эндпоинты
requirements.txt  — зависимости
```

## Запуск

### 1. Применить схему к базе
```bash
psql -h localhost -p 5433 -U arman -d arman -f schema.sql
psql -h localhost -p 5433 -U arman -d arman -f seed.sql   # опционально: тестовые данные
```
> Если psql не в PATH — открой Postgres.app, нажми **Connect…** (откроется psql),
> либо вызови напрямую: `/Applications/Postgres.app/Contents/Versions/latest/bin/psql ...`

### 2. Поднять backend
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 3. Проверить
- Swagger / OpenAPI: http://localhost:8000/docs
- Health: http://localhost:8000/health → `{"status":"ok","db":true}`
- С seed-данными: http://localhost:8000/services и http://localhost:8000/unmatched

Другая строка подключения? Задай переменную окружения:
```bash
export DATABASE_URL="postgresql://user:pass@host:5433/dbname"
```

## Эндпоинты (раздел 4.5 ТЗ)
| Метод | Endpoint | Назначение |
|-------|----------|------------|
| GET | `/services` | Список услуг справочника (фильтр по категории) |
| GET | `/services/{id}/partners` | Кто оказывает услугу + цены |
| GET | `/partners` | Партнёры (фильтр по городу/статусу) |
| GET | `/partners/{id}/services` | Все услуги партнёра + цены |
| GET | `/search?q=` | Нечёткий поиск по услугам и партнёрам (pg_trgm) |
| GET | `/unmatched` | Очередь несопоставленных позиций (операторам) |
| POST | `/match` | Ручное сопоставление позиции со справочником |
| POST | `/items` | Парсер кладёт извлечённую позицию прайса |
| GET | `/stats` | Метрики для дашборда (% нормализации, статусы) |

## Контракт для команды
- **Парсеры** → шлют `POST /items` объектами `PriceItemIn` (см. `models.py`).
- **Нормализатор** → проставляет `service_id` и `match_confidence` у `price_item`
  (точное совпадение → синонимы → нечёткий поиск; порог ≈0.85).
- **Фронт** → читает `/search`, `/services/{id}/partners`, `/unmatched`; пишет `/match`.
- Поля в `models.py` — общий язык. Меняешь поле → предупреди команду.
