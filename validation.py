from __future__ import annotations

from collections import defaultdict
from datetime import date

from models import PriceItem


def validate_items(items: list[PriceItem]) -> list[str]:
    warnings: list[str] = []
    warnings.extend(_validate_values(items))
    warnings.extend(_validate_duplicates(items))
    return warnings


def _validate_values(items: list[PriceItem]) -> list[str]:
    warnings: list[str] = []
    for item in items:
        if not item.service_name_raw.strip():
            warnings.append(f"empty service name in item {item.item_id}")
        if not _has_positive_price(item):
            warnings.append(f"no positive price: {item.service_name_raw}")
        if _nonresident_less_than_resident(item):
            warnings.append(f"nonresident < resident: {item.service_name_raw}")
        if item.effective_date and item.effective_date > date.today():
            warnings.append(f"future price date: {item.service_name_raw}")
    return warnings


def _validate_duplicates(items: list[PriceItem]) -> list[str]:
    grouped = defaultdict(list)
    for item in items:
        key = (item.partner_id, item.service_name_raw.lower(), item.effective_date)
        grouped[key].append(item)
    return [f"duplicate position: {key[1]}" for key, group in grouped.items() if len(group) > 1]


def _has_positive_price(item: PriceItem) -> bool:
    return any(price and price > 0 for price in [item.price_resident_kzt, item.price_nonresident_kzt, item.price_original])


def _nonresident_less_than_resident(item: PriceItem) -> bool:
    if item.price_resident_kzt is None or item.price_nonresident_kzt is None:
        return False
    return item.price_nonresident_kzt < item.price_resident_kzt
