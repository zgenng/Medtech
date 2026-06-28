"""REST API MedArchive (Этап 4 PIPELINE_PLAN, ТЗ 4.5).

Запуск:  uvicorn main:app --reload
Swagger: http://127.0.0.1:8000/docs

Слой тонкий: вся работа с БД — через repository.py (тот же контракт, что у
нормализатора и загрузчика). Pydantic-схемы описывают ответы для /docs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import repository

app = FastAPI(
    title="MedArchive API",
    version="1.0",
    description="Поиск услуг и партнёров по нормализованному архиву прайсов.",
)

# Консоль оператора может открываться с другого origin (preview-панель, отдельный
# статический сервер) — разрешаем CORS, чтобы fetch из UI доходил до API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"


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
    service_code_source: str | None = None


class Candidate(BaseModel):
    service_id: str
    service_name: str
    category: str | None = None
    synonyms: list[str] = []
    sim: float = Field(description="Близость pg_trgm 0..1")


class ReviewItem(BaseModel):
    item_id: str
    service_name_raw: str
    service_id: str | None = None
    service_name: str | None = None
    partner_id: str | None = None
    partner_name: str | None = None
    city: str | None = None
    price_resident_kzt: float | None = None
    price_nonresident_kzt: float | None = None
    price_original: float | None = None
    currency_original: str | None = None
    effective_date: Any | None = None
    match_confidence: float | None = None
    verification_note: str | None = None


class DocumentRow(BaseModel):
    doc_id: str
    file_name: str
    file_format: str | None = None
    parse_status: str | None = None
    partner_name: str | None = None
    effective_date: Any | None = None
    parsed_at: Any | None = None
    items: int = 0


class MatchIn(BaseModel):
    item_id: str
    service_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class VerifyIn(BaseModel):
    item_id: str
    verified: bool = True
    note: str | None = None


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


@app.get("/suggest", response_model=list[Candidate])
def suggest(q: str = Query(min_length=2), limit: int = Query(default=8, le=50)) -> list[dict[str, Any]]:
    """Кандидаты из справочника для ручного сопоставления (ТЗ 4.3)."""
    return repository.trgm_candidates(q, limit=limit)


@app.get("/review", response_model=list[ReviewItem])
def get_review(limit: int = Query(default=100, le=500)) -> list[dict[str, Any]]:
    """Очередь верификации: сопоставлено, но не подтверждено (ТЗ 4.4)."""
    return repository.review_queue(limit=limit)


@app.get("/documents", response_model=list[DocumentRow])
def get_documents(limit: int = Query(default=100, le=500)) -> list[dict[str, Any]]:
    return repository.list_documents(limit=limit)


@app.post("/match")
def post_match(body: MatchIn) -> dict[str, str]:
    repository.update_match(body.item_id, body.service_id, body.confidence)
    return {"status": "ok", "item_id": body.item_id}


@app.post("/verify")
def post_verify(body: VerifyIn) -> dict[str, str]:
    repository.set_verification(body.item_id, body.verified, body.note)
    return {"status": "ok", "item_id": body.item_id}


@app.post("/catalog")
async def post_catalog(file: UploadFile = File(...)) -> dict[str, Any]:
    """Загрузка целевого справочника услуг из xlsx (ТЗ 2.2)."""
    import tempfile

    from normalizer.catalog import load_services_from_xlsx

    suffix = Path(file.filename or "catalog.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        records = load_services_from_xlsx(tmp_path)
        if not records:
            raise HTTPException(status_code=400, detail="В справочнике не найдено услуг (проверьте колонку с названием).")
        result = repository.upsert_services(records)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Не удалось загрузить справочник: {exc}") from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return {"file": file.filename, **result}


@app.post("/upload")
async def post_upload(file: UploadFile = File(...), normalize: bool = True) -> dict[str, Any]:
    """Приём ZIP-архива и запуск пайплинга в БД (ТЗ 4.1, админ-раздел 4.6)."""
    import tempfile

    from config import ParserConfig
    from pipeline import run

    suffix = Path(file.filename or "archive.zip").suffix or ".zip"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        summary = run(tmp_path, config=ParserConfig(), to_db=True, normalize=normalize)
    except Exception as exc:  # noqa: BLE001 — вернуть оператору причину, не падать
        raise HTTPException(status_code=400, detail=f"Не удалось обработать архив: {exc}") from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return {
        "file": file.filename,
        "parse_report": summary.get("parse_report"),
        "save_report": summary.get("save_report"),
        "normalize_stats": summary.get("normalize_stats"),
    }


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


# --- Веб-интерфейс оператора (ТЗ 4.6) ---------------------------------------
# Монтируем в самом конце, чтобы API-маршруты имели приоритет над статикой.

if STATIC_DIR.is_dir():

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
