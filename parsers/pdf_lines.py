from __future__ import annotations

import re

from models import PriceDocument, PriceItem
from utils.currency import detect_currency
from utils.prices import split_trailing_prices
from utils.text import clean_text, is_noise, looks_like_section

_CODE_RE = re.compile(r"^([A-Za-zА-Яа-я]\d[\w.\-/]*|[A-ZА-Я]{1,4}\d[\w.\-/]*|\d{1,4})\s+(.+)$")


def parse_pdf_lines(lines: list[str], document: PriceDocument) -> list[PriceItem]:
    items: list[PriceItem] = []
    pending = ""
    for number, raw_line in enumerate(lines, start=1):
        pending, item = _consume_line(raw_line, pending, document)
        if item:
            item.source_row = number
            items.append(item)
    return items


def _consume_line(raw_line: str, pending: str, document: PriceDocument) -> tuple[str, PriceItem | None]:
    line = clean_text(raw_line)
    if _skip_line(line):
        return "", None
    name, prices = split_trailing_prices(line)
    if not prices:
        return _join_text(pending, line), None
    full_name = _join_text(pending, name)
    currency = detect_currency(line) or "KZT"
    return "", _make_item(full_name, prices, document, currency)


def _make_item(name: str, prices, document: PriceDocument, currency: str = "KZT") -> PriceItem | None:
    code, service_name = _split_code(name)
    if len(service_name) < 3:
        return None
    resident = _resident_price(prices)
    nonresident = _nonresident_price(prices)
    return PriceItem(
        doc_id=document.doc_id,
        partner_id=document.partner_id,
        service_name_raw=service_name,
        service_code_source=code,
        price_resident_kzt=resident,
        price_nonresident_kzt=nonresident,
        price_original=resident,
        currency_original=currency,
        effective_date=document.effective_date,
    )


def _resident_price(prices):
    return prices[0] if prices else None


def _nonresident_price(prices):
    return prices[-1] if len(prices) > 1 else None


def _skip_line(line: str) -> bool:
    return not line or is_noise(line) or looks_like_section(line)


def _join_text(left: str, right: str) -> str:
    return f"{left} {right}".strip() if left else right.strip()


def _split_code(text: str) -> tuple[str | None, str]:
    match = _CODE_RE.match(text)
    if not match:
        return None, text.strip()
    return match.group(1), match.group(2).strip()
