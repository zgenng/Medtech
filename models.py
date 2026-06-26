"""Pydantic-схемы для запросов/ответов API.

Это «контракт» между сервисами: парсер пишет PriceItemIn,
фронт читает ServiceOut / PartnerOut / PriceItemOut.
Меняешь поле здесь — предупреди команду.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


# ---------- Service (справочник) ----------
class ServiceOut(BaseModel):
    service_id: UUID
    service_name: str
    synonyms: list[str] = []
    category: Optional[str] = None
    icd_code: Optional[str] = None
    is_active: bool = True


# ---------- Partner ----------
class PartnerOut(BaseModel):
    partner_id: UUID
    name: str
    city: Optional[str] = None
    address: Optional[str] = None
    bin: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------- PriceItem ----------
class PriceItemOut(BaseModel):
    item_id: UUID
    doc_id: Optional[UUID] = None
    partner_id: Optional[UUID] = None
    partner_name: Optional[str] = None
    service_name_raw: str
    service_id: Optional[UUID] = None
    service_name: Optional[str] = None
    price_resident_kzt: Optional[Decimal] = None
    price_nonresident_kzt: Optional[Decimal] = None
    currency_original: Optional[str] = "KZT"
    is_verified: bool = False
    match_confidence: Optional[Decimal] = None
    effective_date: Optional[date] = None


# Что присылает парсер для одной строки прайса
class PriceItemIn(BaseModel):
    doc_id: UUID
    partner_id: UUID
    service_name_raw: str
    service_code_source: Optional[str] = None
    price_resident_kzt: Optional[Decimal] = None
    price_nonresident_kzt: Optional[Decimal] = None
    price_original: Optional[Decimal] = None
    currency_original: str = "KZT"
    effective_date: Optional[date] = None


# Тело запроса на ручное сопоставление
class MatchRequest(BaseModel):
    item_id: UUID
    service_id: UUID
    verification_note: Optional[str] = None
