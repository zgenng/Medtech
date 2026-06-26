"""MedArchive — backend API (FastAPI).

Запуск:  uvicorn main:app --reload --port 8000
Доки:    http://localhost:8000/docs   (Swagger / OpenAPI — генерируется автоматически)

Эндпоинты соответствуют разделу 4.5 ТЗ. Часть из них уже рабочие
(читают из БД), часть помечена TODO — её добивают по ходу хакатона.
"""
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from db import get_cursor
from models import (
    MatchRequest,
    PartnerOut,
    PriceItemIn,
    PriceItemOut,
    ServiceOut,
)

app = FastAPI(
    title="MedArchive API",
    description="Обработка архива прайсов клиник-партнёров: услуги, цены, поиск.",
    version="0.1.0",
)

# Чтобы фронт (другой порт) мог обращаться к API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health():
    """Проверка, что API и БД живы."""
    with get_cursor() as cur:
        cur.execute("SELECT 1 AS ok;")
        return {"status": "ok", "db": cur.fetchone()["ok"] == 1}


# ============================================================
# Услуги справочника
# ============================================================
@app.get("/services", response_model=list[ServiceOut], tags=["services"])
def list_services(category: Optional[str] = None):
    """Список услуг справочника с фильтрацией по категории."""
    sql = "SELECT * FROM service WHERE is_active = TRUE"
    params: list = []
    if category:
        sql += " AND category = %s"
        params.append(category)
    sql += " ORDER BY service_name LIMIT 500;"
    with get_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@app.get("/services/{service_id}/partners", response_model=list[PriceItemOut], tags=["services"])
def partners_for_service(service_id: UUID):
    """Партнёры, оказывающие услугу, с ценами резидент/нерезидент."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT i.item_id, i.doc_id, i.partner_id, p.name AS partner_name,
                   i.service_name_raw, i.service_id, s.service_name,
                   i.price_resident_kzt, i.price_nonresident_kzt,
                   i.currency_original, i.is_verified, i.match_confidence,
                   i.effective_date
            FROM price_item i
            JOIN partner p ON p.partner_id = i.partner_id
            LEFT JOIN service s ON s.service_id = i.service_id
            WHERE i.service_id = %s AND i.is_active = TRUE
            ORDER BY i.price_resident_kzt NULLS LAST;
            """,
            [service_id],
        )
        return cur.fetchall()


# ============================================================
# Партнёры
# ============================================================
@app.get("/partners", response_model=list[PartnerOut], tags=["partners"])
def list_partners(city: Optional[str] = None, active: Optional[bool] = None):
    """Список партнёров с фильтрацией по городу и статусу."""
    sql = "SELECT * FROM partner WHERE TRUE"
    params: list = []
    if city:
        sql += " AND city = %s"
        params.append(city)
    if active is not None:
        sql += " AND is_active = %s"
        params.append(active)
    sql += " ORDER BY name LIMIT 500;"
    with get_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@app.get("/partners/{partner_id}/services", response_model=list[PriceItemOut], tags=["partners"])
def services_for_partner(partner_id: UUID):
    """Все услуги конкретного партнёра с ценами."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT i.item_id, i.doc_id, i.partner_id, p.name AS partner_name,
                   i.service_name_raw, i.service_id, s.service_name,
                   i.price_resident_kzt, i.price_nonresident_kzt,
                   i.currency_original, i.is_verified, i.match_confidence,
                   i.effective_date
            FROM price_item i
            JOIN partner p ON p.partner_id = i.partner_id
            LEFT JOIN service s ON s.service_id = i.service_id
            WHERE i.partner_id = %s AND i.is_active = TRUE
            ORDER BY s.service_name NULLS LAST, i.service_name_raw;
            """,
            [partner_id],
        )
        return cur.fetchall()


# ============================================================
# Поиск
# ============================================================
@app.get("/search", tags=["search"])
def search(q: str = Query(..., min_length=2)):
    """Полнотекстовый/нечёткий поиск по услугам и партнёрам (pg_trgm)."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT service_id, service_name, category,
                   similarity(service_name, %s) AS score
            FROM service
            WHERE service_name %% %s
            ORDER BY score DESC LIMIT 20;
            """,
            [q, q],
        )
        services = cur.fetchall()
        cur.execute(
            """
            SELECT partner_id, name, city,
                   similarity(name, %s) AS score
            FROM partner
            WHERE name %% %s
            ORDER BY score DESC LIMIT 20;
            """,
            [q, q],
        )
        partners = cur.fetchall()
    return {"services": services, "partners": partners}


# ============================================================
# Очередь верификации (человек-в-цикле)
# ============================================================
@app.get("/unmatched", response_model=list[PriceItemOut], tags=["review"])
def unmatched(limit: int = 100):
    """Несопоставленные позиции (service_id IS NULL) — для операторов."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT i.item_id, i.doc_id, i.partner_id, p.name AS partner_name,
                   i.service_name_raw, i.service_id, NULL AS service_name,
                   i.price_resident_kzt, i.price_nonresident_kzt,
                   i.currency_original, i.is_verified, i.match_confidence,
                   i.effective_date
            FROM price_item i
            LEFT JOIN partner p ON p.partner_id = i.partner_id
            WHERE i.service_id IS NULL AND i.is_active = TRUE
            ORDER BY i.created_at DESC LIMIT %s;
            """,
            [limit],
        )
        return cur.fetchall()


@app.post("/match", tags=["review"])
def manual_match(req: MatchRequest):
    """Ручное сопоставление позиции прайса с услугой справочника."""
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE price_item
            SET service_id = %s, is_verified = TRUE, verification_note = %s
            WHERE item_id = %s
            RETURNING item_id;
            """,
            [req.service_id, req.verification_note, req.item_id],
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Позиция не найдена")
    return {"matched": str(req.item_id), "service_id": str(req.service_id)}


# ============================================================
# Приём данных от парсера
# ============================================================
@app.post("/items", tags=["ingest"])
def add_item(item: PriceItemIn):
    """Парсер кладёт сюда одну извлечённую позицию прайса.
    Нормализация (привязка service_id) — отдельным шагом/сервисом.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO price_item
                (doc_id, partner_id, service_name_raw, service_code_source,
                 price_resident_kzt, price_nonresident_kzt, price_original,
                 currency_original, effective_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
            RETURNING item_id;
            """,
            [
                item.doc_id, item.partner_id, item.service_name_raw,
                item.service_code_source, item.price_resident_kzt,
                item.price_nonresident_kzt, item.price_original,
                item.currency_original, item.effective_date,
            ],
        )
        row = cur.fetchone()
    return {"item_id": str(row["item_id"]) if row else None}


# ============================================================
# Дашборд / метрики обработки
# ============================================================
@app.get("/stats", tags=["system"])
def stats():
    """Метрики для дашборда: статусы документов и % нормализации."""
    with get_cursor() as cur:
        cur.execute("SELECT parse_status, count(*) FROM price_document GROUP BY parse_status;")
        by_status = {r["parse_status"]: r["count"] for r in cur.fetchall()}
        cur.execute(
            """
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE service_id IS NOT NULL) AS matched,
                count(*) FILTER (WHERE service_id IS NULL) AS unmatched
            FROM price_item WHERE is_active = TRUE;
            """
        )
        items = cur.fetchone()
    total = items["total"] or 0
    pct = round(100 * items["matched"] / total, 1) if total else 0.0
    return {
        "documents_by_status": by_status,
        "items_total": total,
        "items_matched": items["matched"],
        "items_unmatched": items["unmatched"],
        "normalization_pct": pct,
    }
