from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from models import PriceDocument, PriceItem
from utils.prices import parse_money
from utils.text import clean_text, is_noise, looks_like_section, normalize_key


@dataclass(slots=True)
class ColumnMap:
    name: int | None = None
    code: int | None = None
    resident: int | None = None
    nonresident: int | None = None
    original: int | None = None


def find_header_index(rows: list[list[object]], max_scan: int = 80) -> int | None:
    scores = [(_header_score(row), i) for i, row in enumerate(rows[:max_scan])]
    score, index = max(scores, default=(0, None))
    return index if score >= 2 else None


def build_column_map(rows: list[list[object]], header_index: int) -> ColumnMap:
    header_rows = rows[header_index: header_index + 3]
    headers = _merged_headers(header_rows)
    return ColumnMap(
        name=_find_col(headers, ["наименование", "услуга", "название"]),
        code=_find_col(headers, ["код", "тарификатор", "мкб"]),
        resident=_find_price_col(headers, ["резидент", "республики казахстан", "рк", "страхов"]),
        nonresident=_find_price_col(headers, ["нерезидент", "снг", "дальнего", "зарубежья"]),
        original=_find_price_col(headers, ["цена", "стоимость", "тариф"]),
    )


def rows_to_items(
    rows: list[list[object]],
    document: PriceDocument,
    columns: ColumnMap,
    start_row: int,
    sheet_name: str | None = None,
) -> list[PriceItem]:
    items: list[PriceItem] = []
    for offset, row in enumerate(rows[start_row:], start=start_row + 1):
        item = row_to_item(row, document, columns, offset, sheet_name)
        if item:
            items.append(item)
    return items


def row_to_item(
    row: list[object],
    document: PriceDocument,
    columns: ColumnMap,
    row_number: int,
    sheet_name: str | None = None,
) -> PriceItem | None:
    name = _cell(row, columns.name)
    if _skip_name(name):
        return None
    prices = _row_prices(row, columns)
    if not any(prices):
        return None
    return PriceItem(
        doc_id=document.doc_id,
        partner_id=document.partner_id,
        service_name_raw=name,
        service_code_source=_cell(row, columns.code) or None,
        price_resident_kzt=prices[0],
        price_nonresident_kzt=prices[1],
        price_original=prices[2] or prices[0] or prices[1],
        currency_original="KZT",
        effective_date=document.effective_date,
        source_row=row_number,
        source_sheet=sheet_name,
    )


def _row_prices(row: list[object], columns: ColumnMap) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    resident = _money_at(row, columns.resident)
    nonresident = _money_at(row, columns.nonresident)
    original = _money_at(row, columns.original)
    if resident is None and original is not None:
        resident = original
    return resident, nonresident, original


def _merged_headers(rows: list[list[object]]) -> list[str]:
    width = max((len(row) for row in rows), default=0)
    headers: list[str] = []
    for index in range(width):
        parts = [clean_text(row[index]) for row in rows if index < len(row) and clean_text(row[index])]
        headers.append(" ".join(parts))
    return headers


def _header_score(row: list[object]) -> int:
    text = normalize_key(" ".join(clean_text(cell) for cell in row))
    keys = ["наименование", "услуг", "цена", "стоимость", "код", "тариф"]
    return sum(1 for key in keys if key in text)


def _find_col(headers: list[str], needles: list[str]) -> int | None:
    for i, header in enumerate(headers):
        key = normalize_key(header)
        if any(needle in key for needle in needles):
            return i
    return None


def _find_price_col(headers: list[str], priorities: list[str]) -> int | None:
    price_cols = [i for i, header in enumerate(headers) if _is_price_header(header)]
    for needle in priorities:
        for i in price_cols:
            if needle in normalize_key(headers[i]):
                return i
    return price_cols[0] if price_cols else None


def _is_price_header(header: str) -> bool:
    key = normalize_key(header)
    return any(word in key for word in ["цена", "стоимость", "тариф", "тенге"])


def _cell(row: list[object], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return clean_text(row[index])


def _money_at(row: list[object], index: int | None) -> Decimal | None:
    if index is None or index >= len(row):
        return None
    return parse_money(row[index])


def _skip_name(name: str) -> bool:
    return not name or is_noise(name) or looks_like_section(name)
