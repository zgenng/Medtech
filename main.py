"""REST API MedArchive (Этап 4 PIPELINE_PLAN, ТЗ 4.5).

Запуск:  uvicorn main:app --reload
Swagger: http://127.0.0.1:8000/docs

Слой тонкий: вся работа с БД — через repository.py (тот же контракт, что у
нормализатора и загрузчика). Pydantic-схемы описывают ответы для /docs.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

import repository

app = FastAPI(
    title="MedArchive API",
    version="1.0",
    description="Поиск услуг и партнёров по нормализованному архиву прайсов.",
)


# --- Pydantic-схемы ответов -------------------------------------------------


class Service(BaseModel):
    service_id: str
    service_name: str
    synonyms: list[str] = []
    category: str | None = None


class ServiceHit(BaseModel):
    service_id: str
    service_name: str
    category: str | None = None
    score: float = Field(description="Близость pg_trgm 0..1")


class PartnerOffer(BaseModel):
    partner_id: str
    name: str
    city: str | None = None
    contact_phone: str | None = None
    price_resident_kzt: float | None = None
    price_nonresident_kzt: float | None = None
    effective_date: Any | None = None
    match_confidence: float | None = None


class Partner(BaseModel):
    partner_id: str
    name: str
    city: str | None = None
    address: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


class PartnerService(BaseModel):
    item_id: str
    service_name_raw: str
    service_id: str | None = None
    service_name: str | None = None
    price_resident_kzt: float | None = None
    price_nonresident_kzt: float | None = None
    effective_date: Any | None = None
    match_confidence: float | None = None


class Unmatched(BaseModel):
    item_id: str
    service_name_raw: str


class MatchIn(BaseModel):
    item_id: str
    service_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ItemIn(BaseModel):
    partner_id: str | None = None
    doc_id: str | None = None
    service_name_raw: str
    service_code_source: str | None = None
    price_resident_kzt: float | None = None
    price_nonresident_kzt: float | None = None
    price_original: float | None = None
    currency_original: str = "KZT"
    effective_date: Any | None = None


# --- Эндпоинты --------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stats")
def get_stats() -> dict[str, Any]:
    return repository.stats()


@app.get("/services", response_model=list[Service])
def get_services(
    q: str | None = Query(default=None, description="Фильтр по имени (ILIKE)"),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> list[dict[str, Any]]:
    return repository.list_services(limit=limit, offset=offset, q=q)


@app.get("/services/{service_id}/partners", response_model=list[PartnerOffer])
def get_service_partners(service_id: str) -> list[dict[str, Any]]:
    return repository.partners_for_service(service_id)


@app.get("/partners", response_model=list[Partner])
def get_partners(limit: int = Query(default=50, le=200), offset: int = 0) -> list[dict[str, Any]]:
    return repository.list_partners(limit=limit, offset=offset)


@app.get("/partners/{partner_id}/services", response_model=list[PartnerService])
def get_partner_services(partner_id: str) -> list[dict[str, Any]]:
    return repository.services_for_partner(partner_id)


@app.get("/search", response_model=list[ServiceHit])
def search(q: str = Query(min_length=2), limit: int = Query(default=20, le=100)) -> list[dict[str, Any]]:
    return repository.search_services(q, limit=limit)


@app.get("/unmatched", response_model=list[Unmatched])
def get_unmatched(limit: int = Query(default=100, le=500)) -> list[dict[str, Any]]:
    return list(repository.iter_unmatched(limit=limit))


@app.post("/match")
def post_match(body: MatchIn) -> dict[str, str]:
    repository.update_match(body.item_id, body.service_id, body.confidence)
    return {"status": "ok", "item_id": body.item_id}


@app.post("/items")
def post_items(items: list[ItemIn]) -> dict[str, int]:
    from decimal import Decimal

    from models import PriceItem

    objs = [
        PriceItem(
            doc_id=it.doc_id,
            partner_id=it.partner_id,
            service_name_raw=it.service_name_raw,
            service_code_source=it.service_code_source,
            price_resident_kzt=None if it.price_resident_kzt is None else Decimal(str(it.price_resident_kzt)),
            price_nonresident_kzt=None if it.price_nonresident_kzt is None else Decimal(str(it.price_nonresident_kzt)),
            price_original=None if it.price_original is None else Decimal(str(it.price_original)),
            currency_original=it.currency_original,
            effective_date=it.effective_date,
        )
        for it in items
    ]
    inserted = repository.bulk_insert_items(objs)
    return {"received": len(items), "inserted": inserted}
