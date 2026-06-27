"""REST API для MedArchive (Этап 2, ТЗ 4.5).

FastAPI поверх ``db.get_cursor``. Поиск партнёров/услуг, нечёткий поиск
(pg_trgm), очередь несопоставленных и ручное сопоставление. Swagger — на /docs.

Запуск:  uvicorn main:app --reload
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

import db

app = FastAPI(
    title="MedArchive API",
    version="1.0",
    description="Архив прайсов клиник-партнёров: поиск услуг, партнёров и цен.",
)


# --- Зависимость БД ------------------------------------------------------
def get_db():
    """Курсор на время запроса; коммит на успешном выходе (для POST)."""
    with db.get_cursor() as cur:
        yield cur


Cursor = Annotated[Any, Depends(get_db)]


# --- Схемы ответов -------------------------------------------------------
class ServiceOut(BaseModel):
    service_id: UUID
    service_name: str
    synonyms: list[str] = []
    category: str | None = None
    icd_code: str | None = None
    is_active: bool = True


class PartnerOut(BaseModel):
    partner_id: UUID
    name: str
    city: str | None = None
    address: str | None = None
    bin: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    is_active: bool = True


class PriceItemOut(BaseModel):
    item_id: UUID
    doc_id: UUID | None = None
    partner_id: UUID | None = None
    service_name_raw: str
    service_code_source: str | None = None
    service_id: UUID | None = None
    price_resident_kzt: Decimal | None = None
    price_nonresident_kzt: Decimal | None = None
    price_original: Decimal | None = None
    currency_original: str | None = None
    is_verified: bool = False
    verification_note: str | None = None
    match_confidence: Decimal | None = None
    effective_date: date | None = None
    is_active: bool = True


class ServicePartnerOut(BaseModel):
    """Кто оказывает услугу + цены резидент/нерезидент."""
    partner_id: UUID
    name: str
    city: str | None = None
    price_resident_kzt: Decimal | None = None
    price_nonresident_kzt: Decimal | None = None
    currency_original: str | None = None
    match_confidence: Decimal | None = None
    effective_date: date | None = None


class MatchIn(BaseModel):
    item_id: UUID
    service_id: UUID
    match_confidence: Decimal | None = Field(default=None, ge=0, le=1)


class ItemIn(BaseModel):
    doc_id: UUID | None = None
    partner_id: UUID | None = None
    service_name_raw: str
    service_code_source: str | None = None
    service_id: UUID | None = None
    price_resident_kzt: Decimal | None = None
    price_nonresident_kzt: Decimal | None = None
    price_original: Decimal | None = None
    currency_original: str = "KZT"
    effective_date: date | None = None


# --- Системные -----------------------------------------------------------
@app.get("/health", tags=["system"])
def health(cur: Cursor) -> dict:
    cur.execute("SELECT 1 AS ok")
    return {"status": "ok", "db": cur.fetchone()["ok"] == 1}


# --- Услуги --------------------------------------------------------------
@app.get("/services", response_model=list[ServiceOut], tags=["services"])
def list_services(
    cur: Cursor,
    category: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    sql = "SELECT * FROM service WHERE (%s::text IS NULL OR category = %s) "
    sql += "ORDER BY service_name LIMIT %s OFFSET %s"
    cur.execute(sql, (category, category, limit, offset))
    return cur.fetchall()


@app.get("/services/{service_id}/partners",
         response_model=list[ServicePartnerOut], tags=["services"])
def service_partners(service_id: str, cur: Cursor) -> list[dict]:
    cur.execute(
        "SELECT p.partner_id, p.name, p.city, "
        "       pi.price_resident_kzt, pi.price_nonresident_kzt, "
        "       pi.currency_original, pi.match_confidence, pi.effective_date "
        "FROM price_item pi "
        "JOIN partner p ON p.partner_id = pi.partner_id "
        "WHERE pi.service_id = %s AND pi.is_active = TRUE "
        "ORDER BY pi.price_resident_kzt NULLS LAST",
        (service_id,),
    )
    return cur.fetchall()


# --- Партнёры ------------------------------------------------------------
@app.get("/partners", response_model=list[PartnerOut], tags=["partners"])
def list_partners(
    cur: Cursor,
    city: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    cur.execute(
        "SELECT * FROM partner "
        "WHERE (%s::text IS NULL OR city = %s) "
        "  AND (%s::boolean IS NULL OR is_active = %s) "
        "ORDER BY name LIMIT %s OFFSET %s",
        (city, city, is_active, is_active, limit, offset),
    )
    return cur.fetchall()


@app.get("/partners/{partner_id}/services",
         response_model=list[PriceItemOut], tags=["partners"])
def partner_services(partner_id: str, cur: Cursor) -> list[dict]:
    cur.execute(
        "SELECT * FROM price_item "
        "WHERE partner_id = %s AND is_active = TRUE "
        "ORDER BY service_name_raw",
        (partner_id,),
    )
    return cur.fetchall()


# --- Поиск ---------------------------------------------------------------
@app.get("/search", response_model=list[PriceItemOut], tags=["search"])
def search(
    cur: Cursor,
    q: str = Query(..., min_length=1, description="Строка поиска по названию услуги"),
    limit: int = Query(20, ge=1, le=200),
) -> list[dict]:
    """Нечёткий поиск по ``service_name_raw`` через pg_trgm (% и similarity)."""
    cur.execute(
        "SELECT *, similarity(service_name_raw, %s) AS score "
        "FROM price_item "
        "WHERE is_active = TRUE "
        "  AND (service_name_raw ILIKE %s OR service_name_raw %% %s) "
        "ORDER BY score DESC, service_name_raw "
        "LIMIT %s",
        (q, f"%{q}%", q, limit),
    )
    return cur.fetchall()


# --- Сопоставление (стык с нормализатором) -------------------------------
@app.get("/unmatched", response_model=list[PriceItemOut], tags=["matching"])
def unmatched(
    cur: Cursor,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    """Очередь несопоставленных позиций (``service_id IS NULL``)."""
    cur.execute(
        "SELECT * FROM price_item "
        "WHERE service_id IS NULL AND is_active = TRUE "
        "ORDER BY created_at DESC LIMIT %s OFFSET %s",
        (limit, offset),
    )
    return cur.fetchall()


@app.post("/match", response_model=PriceItemOut, tags=["matching"])
def match(payload: MatchIn, cur: Cursor) -> dict:
    """Ручное сопоставление: проставить ``service_id`` (+ ``match_confidence``)."""
    cur.execute(
        "UPDATE price_item "
        "SET service_id = %s, match_confidence = %s "
        "WHERE item_id = %s "
        "RETURNING *",
        (payload.service_id, payload.match_confidence, payload.item_id),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="price_item not found")
    return row


@app.post("/items", response_model=PriceItemOut, status_code=201, tags=["matching"])
def create_item(payload: ItemIn, cur: Cursor) -> dict:
    """Приём позиции от парсера/внешнего источника."""
    cols = list(payload.model_fields.keys())
    values = [getattr(payload, c) for c in cols]
    placeholders = ", ".join(["%s"] * len(cols))
    cur.execute(
        f"INSERT INTO price_item ({', '.join(cols)}) VALUES ({placeholders}) "
        "RETURNING *",
        values,
    )
    return cur.fetchone()


# --- Статистика (каркас для этапа 5) -------------------------------------
@app.get("/stats", tags=["dashboard"])
def stats(cur: Cursor) -> dict:
    """Метрики дашборда. Каркас: команда этапа 5 подставляет свой SQL.

    Пока отдаёт базовые счётчики, чтобы эндпоинт был рабочим в Swagger.
    """
    cur.execute(
        "SELECT "
        "  (SELECT count(*) FROM partner)                                  AS partners, "
        "  (SELECT count(*) FROM price_document)                           AS documents, "
        "  (SELECT count(*) FROM price_item WHERE is_active)               AS items_active, "
        "  (SELECT count(*) FROM price_item WHERE service_id IS NULL "
        "                                     AND is_active)                AS items_unmatched, "
        "  (SELECT count(*) FROM service)                                  AS services"
    )
    return cur.fetchone()
