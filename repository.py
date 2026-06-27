"""Слой загрузки распарсенного прайса в Supabase (Этап 1).

Единственное место, где описано соответствие «поле модели → колонка БД».
Поверх ``db.pool``: транзакция на документ (партнёр → документ → позиции),
ошибка одного документа не откатывает остальные. Повторная загрузка того же
файла не плодит дубли (идемпотентность по партнёру + имени файла и по
уникальному индексу ``uq_item_dedup``).
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from psycopg.rows import dict_row

import db
from models import Partner, PriceDocument, PriceItem

# --- Единый маппинг «поле модели → колонка БД» ---------------------------
# Перечислены ровно те колонки, что пишутся вставкой. Служебные поля модели
# (source_row, source_sheet) сюда не входят и в БД не попадают.
PARTNER_COLUMNS: tuple[str, ...] = (
    "partner_id", "name", "city", "address", "bin",
    "contact_email", "contact_phone", "is_active",
)
DOCUMENT_COLUMNS: tuple[str, ...] = (
    "doc_id", "partner_id", "file_name", "file_format", "effective_date",
    "parsed_at", "parse_status", "parse_log", "raw_content", "file_path",
)
ITEM_COLUMNS: tuple[str, ...] = (
    "item_id", "doc_id", "partner_id", "service_name_raw", "service_code_source",
    "service_id", "price_resident_kzt", "price_nonresident_kzt", "price_original",
    "currency_original", "is_verified", "verification_note", "match_confidence",
    "effective_date", "is_active",
)


def _values(obj: Any, columns: Sequence[str]) -> list[Any]:
    return [getattr(obj, col) for col in columns]


def _insert_sql(table: str, columns: Sequence[str], conflict: str = "") -> str:
    cols = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    return f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) {conflict}".strip()


class Repository:
    """Запись распарсенного payload в БД и поиск версий для других этапов."""

    def save(self, payload: dict) -> dict:
        """Сохранить payload от ``ArchiveParser.parse()``. Возвращает отчёт о загрузке."""
        partners_by_id = {p.partner_id: p for p in payload["partners"]}
        documents: list[PriceDocument] = payload["documents"]
        all_items: list[PriceItem] = payload["items"]
        items_by_doc: dict[str, list[PriceItem]] = {}
        for item in all_items:
            items_by_doc.setdefault(item.doc_id, []).append(item)

        report = {"documents_saved": 0, "documents_skipped": 0,
                  "documents_error": 0, "items_inserted": 0}

        with db.pool.connection() as conn:
            for document in documents:
                items = items_by_doc.get(document.doc_id, [])
                partner = partners_by_id.get(document.partner_id) or Partner(
                    name=document.file_name, partner_id=document.partner_id,
                )
                try:
                    with conn.transaction():
                        inserted = self._save_document(conn, partner, document, items)
                    if inserted is None:
                        report["documents_skipped"] += 1
                    else:
                        report["documents_saved"] += 1
                        report["items_inserted"] += inserted
                except Exception as error:  # один плохой документ не валит остальные
                    document.parse_status = "error"
                    document.parse_log = (document.parse_log + f"\nDB: {error}").strip()
                    report["documents_error"] += 1
        return report

    def _save_document(
        self, conn, partner: Partner, document: PriceDocument, items: Iterable[PriceItem],
    ) -> int | None:
        """Партнёр → документ → позиции в одной транзакции.

        Возвращает число вставленных позиций, либо ``None`` если документ уже
        загружался ранее (идемпотентный повтор — пропускаем).
        """
        with conn.cursor(row_factory=dict_row) as cur:
            partner_id = self._upsert_partner(cur, partner)

            existing = self._find_document(cur, partner_id, document.file_name)
            if existing is not None:
                return None

            document.partner_id = partner_id
            cur.execute(_insert_sql("price_document", DOCUMENT_COLUMNS),
                        _values(document, DOCUMENT_COLUMNS))

            return self._bulk_insert_items(cur, items, document.doc_id, partner_id)

    def _upsert_partner(self, cur, partner: Partner) -> str:
        """Дедуп по ``bin``, иначе по ``name`` + ``city``. Возвращает реальный partner_id."""
        if partner.bin:
            cur.execute("SELECT partner_id FROM partner WHERE bin = %s", (partner.bin,))
        else:
            cur.execute(
                "SELECT partner_id FROM partner "
                "WHERE name = %s AND city IS NOT DISTINCT FROM %s",
                (partner.name, partner.city),
            )
        found = cur.fetchone()
        if found:
            return str(found["partner_id"])

        cur.execute(_insert_sql("partner", PARTNER_COLUMNS) + " RETURNING partner_id",
                    _values(partner, PARTNER_COLUMNS))
        return str(cur.fetchone()["partner_id"])

    @staticmethod
    def _find_document(cur, partner_id: str, file_name: str):
        cur.execute(
            "SELECT doc_id FROM price_document WHERE partner_id = %s AND file_name = %s",
            (partner_id, file_name),
        )
        return cur.fetchone()

    @staticmethod
    def _bulk_insert_items(
        cur, items: Iterable[PriceItem], doc_id: str, partner_id: str,
    ) -> int:
        """Пакетная вставка позиций. ON CONFLICT по ``uq_item_dedup`` — без дублей."""
        rows = []
        for item in items:
            item.doc_id = doc_id
            item.partner_id = partner_id
            rows.append(_values(item, ITEM_COLUMNS))
        if not rows:
            return 0

        sql = _insert_sql(
            "price_item", ITEM_COLUMNS,
            "ON CONFLICT (partner_id, service_name_raw, effective_date) "
            "WHERE is_active = TRUE DO NOTHING",
        )
        before = cur.rowcount
        cur.executemany(sql, rows)
        # executemany не агрегирует rowcount надёжно — считаем как число поданных строк
        return len(rows)

    # --- Контракт для этапа версионирования (ТЗ 4.4) ---------------------
    @staticmethod
    def find_active_item(partner_id: str, service_name_raw: str) -> dict | None:
        """Найти предыдущую активную позицию (для версионирования цен)."""
        with db.get_cursor() as cur:
            cur.execute(
                "SELECT * FROM price_item "
                "WHERE partner_id = %s AND service_name_raw = %s AND is_active = TRUE "
                "LIMIT 1",
                (partner_id, service_name_raw),
            )
            return cur.fetchone()
