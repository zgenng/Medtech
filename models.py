from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4


def new_id() -> str:
    return str(uuid4())


@dataclass(slots=True)
class Partner:
    name: str
    city: str | None = None
    address: str | None = None
    bin: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    is_active: bool = True
    partner_id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class PriceDocument:
    partner_id: str
    file_name: str
    file_format: str
    effective_date: date | None = None
    parse_status: str = "pending"
    parse_log: str = ""
    raw_content: str = ""
    file_path: str | None = None  # путь к оригиналу (аудит), колонка price_document.file_path
    doc_id: str = field(default_factory=new_id)
    parsed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class PriceItem:
    doc_id: str
    partner_id: str
    service_name_raw: str
    service_code_source: str | None = None
    service_id: str | None = None          # нормализованная услуга (проставляет нормализатор)
    match_confidence: float | None = None  # уверенность автосопоставления 0..1
    price_resident_kzt: Decimal | None = None
    price_nonresident_kzt: Decimal | None = None
    price_original: Decimal | None = None
    currency_original: str = "KZT"
    is_verified: bool = False
    verification_note: str | None = None
    effective_date: date | None = None
    is_active: bool = True
    source_row: int | None = None
    source_sheet: str | None = None
    item_id: str = field(default_factory=new_id)


@dataclass(slots=True)
class ParseResult:
    document: PriceDocument
    items: list[PriceItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def finalize(self) -> "ParseResult":
        if self.errors:
            self.document.parse_status = "error"
        elif self.warnings:
            self.document.parse_status = "needs_review"
        else:
            self.document.parse_status = "done"
        self.document.parse_log = "\n".join(self.warnings + self.errors)
        return self


def to_plain_dict(obj: Any) -> dict[str, Any]:
    data = asdict(obj)
    for key, value in list(data.items()):
        if isinstance(value, Decimal):
            data[key] = float(value)
        elif isinstance(value, (datetime, date)):
            data[key] = value.isoformat()
    return data
