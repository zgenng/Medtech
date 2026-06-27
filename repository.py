"""Доступ нормализатора к БД через репозиторий (раздел «Интерфейс» ТЗ).

Нормализатор не лезет в БД мимо этого слоя. Импорт db ленивый — модуль
импортируется и без установленного psycopg (например, в офлайн-тестах,
которые работают со списком ServiceRecord напрямую).
"""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from typing import Any, Iterable, Iterator


def _cursor():
    from db import get_cursor  # ленивый импорт, чтобы не требовать psycopg всегда

    return get_cursor()


def load_services() -> list[dict[str, Any]]:
    """Список услуг справочника: service_id, service_name, synonyms, category."""
    with _cursor() as cur:
        cur.execute(
            """
            SELECT service_id, service_name, synonyms, category
            FROM service
            WHERE is_active = TRUE
            """
        )
        rows = cur.fetchall()
    for row in rows:
        row["service_id"] = str(row["service_id"])
        row["synonyms"] = _as_list(row.get("synonyms"))
    return rows


def iter_unmatched(limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Позиции прайса без сопоставления (service_id IS NULL)."""
    sql = """
        SELECT item_id, service_name_raw, service_code_source
        FROM price_item
        WHERE service_id IS NULL AND is_active = TRUE
        ORDER BY created_at
    """
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT %s"
        params = (limit,)
    with _cursor() as cur:
        cur.execute(sql, params)
        for row in cur.fetchall():
            row["item_id"] = str(row["item_id"])
            yield row


def update_match(item_id: str, service_id: str | None, confidence: float | None) -> None:
    """Проставить нормализованную услугу и уверенность для позиции прайса."""
    with _cursor() as cur:
        cur.execute(
            """
            UPDATE price_item
            SET service_id = %s, match_confidence = %s
            WHERE item_id = %s
            """,
            (service_id, confidence, item_id),
        )


def add_synonym(service_id: str, synonym: str) -> None:
    """Обратная связь (§8): подтверждение/исправление оператора → service.synonyms.

    Дедуплицирует против существующих синонимов, не трогает массив, если
    значение уже есть.
    """
    synonym = synonym.strip()
    if not synonym:
        return
    with _cursor() as cur:
        cur.execute(
            """
            UPDATE service
            SET synonyms = synonyms || %s::jsonb
            WHERE service_id = %s
              AND NOT (synonyms @> %s::jsonb)
            """,
            (json.dumps([synonym]), service_id, json.dumps([synonym])),
        )


def trgm_candidates(name: str, limit: int = 50, category: str | None = None) -> list[dict[str, Any]]:
    """Кандидаты через pg_trgm (idx_service_name_trgm) — blocking для большого справочника."""
    sql = """
        SELECT service_id, service_name, synonyms, category,
               similarity(service_name, %s) AS sim
        FROM service
        WHERE is_active = TRUE
          AND (%s IS NULL OR category = %s)
          AND service_name %% %s
        ORDER BY sim DESC
        LIMIT %s
    """
    with _cursor() as cur:
        cur.execute(sql, (name, category, category, name, limit))
        rows = cur.fetchall()
    for row in rows:
        row["service_id"] = str(row["service_id"])
        row["synonyms"] = _as_list(row.get("synonyms"))
    return rows


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return [value]
    return list(value) if isinstance(value, Iterable) and not isinstance(value, (str, bytes)) else []


# ============================================================
# Write-слой (Этап 1 PIPELINE_PLAN): архив → парсер → Supabase
# ============================================================

# Колонки price_item, которые реально пишем. source_row/source_sheet остаются
# на объекте PriceItem для отладки парсинга, но в БД не уходят (служебные).
_ITEM_COLUMNS = (
    "item_id",
    "doc_id",
    "partner_id",
    "service_name_raw",
    "service_code_source",
    "service_id",
    "price_resident_kzt",
    "price_nonresident_kzt",
    "price_original",
    "currency_original",
    "is_verified",
    "verification_note",
    "match_confidence",
    "effective_date",
    "is_active",
)

# Порог ценовой аномалии (ТЗ 4.4): изменение цены > 50% относительно предыдущей
# версии → флаг для ручного подтверждения.
_ANOMALY_THRESHOLD = Decimal("0.5")


def _upsert_partner(cur, partner) -> str:
    """Дедуп партнёра: по bin, иначе по name+city. Возвращает partner_id из БД.

    Важно: id берём из БД, а НЕ partner.partner_id (сгенерированный парсером), —
    save() по нему ремаппит документы и позиции.
    """
    if partner.bin:
        cur.execute("SELECT partner_id FROM partner WHERE bin = %s LIMIT 1", (partner.bin,))
    else:
        cur.execute(
            "SELECT partner_id FROM partner "
            "WHERE name = %s AND city IS NOT DISTINCT FROM %s LIMIT 1",
            (partner.name, partner.city),
        )
    row = cur.fetchone()
    if row:
        return str(row["partner_id"])
    cur.execute(
        """
        INSERT INTO partner (name, city, address, bin, contact_email, contact_phone, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING partner_id
        """,
        (
            partner.name,
            partner.city,
            partner.address,
            partner.bin,
            partner.contact_email,
            partner.contact_phone,
            partner.is_active,
        ),
    )
    return str(cur.fetchone()["partner_id"])


def _insert_document(cur, document, partner_id: str) -> str:
    """Upsert документа по (partner_id, file_name) — идемпотентно по файлу.

    Тот же файл той же клиники переиспользует doc_id (uq_document_file), повторный
    прогон не плодит документы. Возвращает doc_id из БД.
    """
    cur.execute(
        """
        INSERT INTO price_document
            (partner_id, file_name, file_format, effective_date, parsed_at,
             parse_status, parse_log, raw_content, file_path)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (partner_id, file_name) DO UPDATE SET
            file_format    = EXCLUDED.file_format,
            effective_date = EXCLUDED.effective_date,
            parsed_at      = EXCLUDED.parsed_at,
            parse_status   = EXCLUDED.parse_status,
            parse_log      = EXCLUDED.parse_log,
            raw_content    = EXCLUDED.raw_content,
            file_path      = EXCLUDED.file_path
        RETURNING doc_id
        """,
        (
            partner_id,
            document.file_name,
            document.file_format,
            document.effective_date,
            document.parsed_at,
            document.parse_status,
            document.parse_log,
            document.raw_content,
            document.file_path,
        ),
    )
    return str(cur.fetchone()["doc_id"])


def _bulk_insert_items(cur, items) -> int:
    """Вставка позиций с версионированием цен (ТЗ 4.4/5). Возвращает число
    реально вставленных строк (идемпотентные дубли пропускаются).

    На позицию:
      * точно такая же версия (та же дата и цены) уже есть → пропуск (идемпотентность);
      * активной версии услуги нет → вставка как активной;
      * пришла более новая (или равная по дате) цена → старую активную архивируем
        (is_active=FALSE, история не удаляется), новую делаем активной; при
        изменении > 50% ставим флаг ценовой аномалии на ручное подтверждение;
      * пришёл более старый прайс → кладём в историю (is_active=FALSE), текущую
        активную цену не трогаем.
    """
    inserted = 0
    for item in items:
        inserted += _save_item_versioned(cur, item)
    return inserted


def _save_item_versioned(cur, item) -> int:
    if _identical_version_exists(cur, item):
        return 0  # такая же версия уже записана — повторный прогон ничего не меняет

    current = _current_active_item(cur, item)
    if current is None:
        item.is_active = True
        _insert_one_item(cur, item)
        return 1

    if _is_newer_or_equal(item.effective_date, current["effective_date"]):
        _flag_anomaly_if_big(current, item)
        cur.execute("UPDATE price_item SET is_active = FALSE WHERE item_id = %s", (current["item_id"],))
        item.is_active = True
    else:
        item.is_active = False  # более старый прайс — только в историю
    _insert_one_item(cur, item)
    return 1


def _identical_version_exists(cur, item) -> bool:
    """Есть ли уже строка с тем же ключом (партнёр+услуга+дата) и теми же ценами.

    Покрывает идемпотентность и для активных, и для архивных версий, поэтому
    повторная загрузка того же файла не плодит дубли.
    """
    cur.execute(
        """
        SELECT 1 FROM price_item
        WHERE partner_id = %s AND service_name_raw = %s
          AND COALESCE(effective_date, DATE '0001-01-01') = COALESCE(%s, DATE '0001-01-01')
          AND price_resident_kzt    IS NOT DISTINCT FROM %s
          AND price_nonresident_kzt IS NOT DISTINCT FROM %s
          AND price_original        IS NOT DISTINCT FROM %s
        LIMIT 1
        """,
        (
            item.partner_id,
            item.service_name_raw,
            item.effective_date,
            item.price_resident_kzt,
            item.price_nonresident_kzt,
            item.price_original,
        ),
    )
    return cur.fetchone() is not None


def _current_active_item(cur, item) -> dict[str, Any] | None:
    """Текущая активная версия услуги у партнёра (uq_item_active гарантирует ≤1)."""
    cur.execute(
        """
        SELECT item_id, effective_date,
               price_resident_kzt, price_nonresident_kzt, price_original
        FROM price_item
        WHERE partner_id = %s AND service_name_raw = %s AND is_active = TRUE
        LIMIT 1
        """,
        (item.partner_id, item.service_name_raw),
    )
    return cur.fetchone()


def _insert_one_item(cur, item) -> None:
    cols = ", ".join(_ITEM_COLUMNS)
    placeholders = ", ".join(["%s"] * len(_ITEM_COLUMNS))
    cur.execute(
        f"INSERT INTO price_item ({cols}) VALUES ({placeholders})",
        tuple(getattr(item, col) for col in _ITEM_COLUMNS),
    )


def _flag_anomaly_if_big(current: dict[str, Any], item) -> None:
    """ТЗ 4.4: цена отличается от предыдущей версии > 50% → флаг аномалии."""
    ratio = _price_change_ratio(_repr_price_row(current), _repr_price_item(item))
    if ratio is None or ratio <= _ANOMALY_THRESHOLD:
        return
    note = f"ценовая аномалия: изменение {ratio * 100:.0f}% относительно предыдущей версии"
    item.verification_note = f"{item.verification_note}; {note}" if item.verification_note else note
    item.is_verified = False  # требует ручного подтверждения оператором


def _repr_price_item(item) -> Decimal | None:
    return _repr_price(item.price_resident_kzt, item.price_original, item.price_nonresident_kzt)


def _repr_price_row(row: dict[str, Any]) -> Decimal | None:
    return _repr_price(row.get("price_resident_kzt"), row.get("price_original"), row.get("price_nonresident_kzt"))


def _repr_price(*candidates) -> Decimal | None:
    for price in candidates:
        if price is not None:
            return Decimal(str(price))
    return None


def _price_change_ratio(old: Decimal | None, new: Decimal | None) -> Decimal | None:
    if old is None or new is None or old == 0:
        return None
    return abs(new - old) / abs(old)


def _is_newer_or_equal(new_date, current_date) -> bool:
    """Новее ли (или равна по дате) пришедшая цена. None трактуем как «нет даты»:
    датированная цена считается новее недатированной, две недатированные — равны."""
    if new_date is None and current_date is None:
        return True
    if new_date is None:
        return False
    if current_date is None:
        return True
    return new_date >= current_date


def save(payload: dict) -> dict:
    """Сохранить payload парсера в Supabase. Транзакция на документ.

    Порядок на документ: партнёр → документ → позиции, всё в одной транзакции.
    Любая ошибка → откат всего документа; затем в ОТДЕЛЬНОЙ транзакции документ
    помечается parse_status='error' (после отката основной строки уже нет, поэтому
    статус пишется заново). Возвращает сводку для отчёта пайплайна.
    """
    documents = payload.get("documents", [])
    partners_by_pid = {p.partner_id: p for p in payload.get("partners", [])}
    items_by_doc: dict[str, list] = defaultdict(list)
    for item in payload.get("items", []):
        items_by_doc[item.doc_id].append(item)

    report = {"documents_saved": 0, "documents_error": 0, "items_inserted": 0, "errors": []}
    for document in documents:
        doc_items = items_by_doc.get(document.doc_id, [])
        src_partner = partners_by_pid.get(document.partner_id) or _partner_fallback(document)
        try:
            with _cursor() as cur:
                db_partner_id = _upsert_partner(cur, src_partner)
                db_doc_id = _insert_document(cur, document, db_partner_id)
                # ремаппинг: parser-id → db-id, иначе FK на partner/doc не сойдётся
                for item in doc_items:
                    item.partner_id = db_partner_id
                    item.doc_id = db_doc_id
                report["items_inserted"] += _bulk_insert_items(cur, doc_items)
            report["documents_saved"] += 1
        except Exception as exc:  # noqa: BLE001 — фиксируем и идём дальше по архиву
            report["documents_error"] += 1
            report["errors"].append(f"{document.file_name}: {exc}")
            _mark_document_error(document, src_partner, str(exc))
    return report


def _mark_document_error(document, src_partner, message: str) -> None:
    """Пометить документ parse_status='error' в отдельной транзакции (best-effort)."""
    try:
        with _cursor() as cur:
            db_partner_id = _upsert_partner(cur, src_partner)
            document.parse_status = "error"
            document.parse_log = (f"{document.parse_log}\nload error: {message}").strip()
            _insert_document(cur, document, db_partner_id)
    except Exception:  # noqa: BLE001 — вторичный сбой не должен валить загрузку
        pass


def _partner_fallback(document):
    """Партнёр на случай, если payload не дал его (обычно парсер даёт всегда)."""
    from models import Partner

    return Partner(name=document.file_name)


# --- Публичные обёртки (по контракту PIPELINE_PLAN), каждая в своей транзакции ---


def upsert_partner(partner) -> str:
    with _cursor() as cur:
        return _upsert_partner(cur, partner)


def insert_document(document, partner_id: str | None = None) -> str:
    with _cursor() as cur:
        return _insert_document(cur, document, partner_id or document.partner_id)


def bulk_insert_items(items) -> int:
    with _cursor() as cur:
        return _bulk_insert_items(cur, items)


# ============================================================
# Read-слой для REST API (Этап 4 PIPELINE_PLAN)
# ============================================================


def list_services(limit: int = 50, offset: int = 0, q: str | None = None) -> list[dict[str, Any]]:
    """Справочник услуг с пагинацией и опциональным фильтром по имени."""
    sql = """
        SELECT service_id, service_name, synonyms, category
        FROM service
        WHERE is_active = TRUE
          AND (%s::text IS NULL OR service_name ILIKE '%%' || %s::text || '%%')
        ORDER BY service_name
        LIMIT %s OFFSET %s
    """
    with _cursor() as cur:
        cur.execute(sql, (q, q, limit, offset))
        rows = cur.fetchall()
    for row in rows:
        row["service_id"] = str(row["service_id"])
        row["synonyms"] = _as_list(row.get("synonyms"))
    return rows


def partners_for_service(service_id: str) -> list[dict[str, Any]]:
    """Партнёры, предлагающие услугу, с ценами (для «найти услугу → клиники»)."""
    sql = """
        SELECT p.partner_id, p.name, p.city, p.contact_phone,
               pi.price_resident_kzt, pi.price_nonresident_kzt,
               pi.effective_date, pi.match_confidence
        FROM price_item pi
        JOIN partner p ON p.partner_id = pi.partner_id
        WHERE pi.service_id = %s AND pi.is_active = TRUE
        ORDER BY pi.price_resident_kzt NULLS LAST
    """
    with _cursor() as cur:
        cur.execute(sql, (service_id,))
        rows = cur.fetchall()
    for row in rows:
        row["partner_id"] = str(row["partner_id"])
    return rows


def list_partners(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    sql = """
        SELECT partner_id, name, city, address, contact_email, contact_phone
        FROM partner
        WHERE is_active = TRUE
        ORDER BY name
        LIMIT %s OFFSET %s
    """
    with _cursor() as cur:
        cur.execute(sql, (limit, offset))
        rows = cur.fetchall()
    for row in rows:
        row["partner_id"] = str(row["partner_id"])
    return rows


def services_for_partner(partner_id: str) -> list[dict[str, Any]]:
    """Прайс партнёра: сырое имя, нормализованная услуга (если есть), цены."""
    sql = """
        SELECT pi.item_id, pi.service_name_raw, pi.service_id, s.service_name,
               pi.price_resident_kzt, pi.price_nonresident_kzt,
               pi.effective_date, pi.match_confidence
        FROM price_item pi
        LEFT JOIN service s ON s.service_id = pi.service_id
        WHERE pi.partner_id = %s AND pi.is_active = TRUE
        ORDER BY pi.service_name_raw
    """
    with _cursor() as cur:
        cur.execute(sql, (partner_id,))
        rows = cur.fetchall()
    for row in rows:
        row["item_id"] = str(row["item_id"])
        row["service_id"] = str(row["service_id"]) if row["service_id"] else None
    return rows


def search_services(q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Нечёткий поиск услуги по справочнику через pg_trgm (idx_service_name_trgm)."""
    sql = """
        SELECT service_id, service_name, category,
               similarity(service_name, %s) AS score
        FROM service
        WHERE is_active = TRUE AND service_name %% %s
        ORDER BY score DESC
        LIMIT %s
    """
    with _cursor() as cur:
        cur.execute(sql, (q, q, limit))
        rows = cur.fetchall()
    for row in rows:
        row["service_id"] = str(row["service_id"])
        row["score"] = float(row["score"])
    return rows


def stats() -> dict[str, Any]:
    """Сводные метрики для дашборда (ТЗ 4.6): документы, нормализация, очереди."""
    with _cursor() as cur:
        cur.execute("SELECT count(*) n FROM partner WHERE is_active")
        partners = cur.fetchone()["n"]
        cur.execute("SELECT count(*) n FROM service WHERE is_active")
        services = cur.fetchone()["n"]
        cur.execute(
            """
            SELECT parse_status, count(*) n
            FROM price_document GROUP BY parse_status
            """
        )
        by_status = {r["parse_status"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            """
            SELECT
                count(*) FILTER (WHERE is_active)                                  AS items_total,
                count(*) FILTER (WHERE is_active AND service_id IS NOT NULL)        AS items_matched,
                count(*) FILTER (WHERE is_active AND service_id IS NULL)            AS items_unmatched
            FROM price_item
            """
        )
        items = cur.fetchone()
    total = items["items_total"] or 0
    matched = items["items_matched"] or 0
    return {
        "partners": partners,
        "services": services,
        "documents_total": sum(by_status.values()),
        "documents_by_status": by_status,
        "items_total": total,
        "items_matched": matched,
        "items_unmatched": items["items_unmatched"] or 0,
        "auto_match_pct": round(100 * matched / total, 1) if total else 0.0,
    }
