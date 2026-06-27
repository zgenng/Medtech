from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_PRICE_TOKEN = re.compile(
    r"(?<![A-Za-zА-Яа-я])(?:[0-9IІlОOСC]{1,3}(?:[\s.,][0-9OОСC]{3})+|[0-9IІlОOСC]{3,})(?:[.,][0-9]{1,2})?(?![A-Za-zА-Яа-я])"
)

_TRANSLATION = str.maketrans({
    "O": "0", "О": "0", "о": "0",
    "C": "0", "С": "0", "с": "0",
    "I": "1", "І": "1", "l": "1",
})


def normalize_money_text(value: object) -> str:
    text = str(value).translate(_TRANSLATION)
    text = re.sub(r"[^0-9,.-]", "", text)
    if text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")
    text = text.replace(",", "")
    return text


def parse_money(value: object) -> Decimal | None:
    text = normalize_money_text(value)
    if not text or text in {"-", "."}:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number > 0 else None


def extract_prices(text: str) -> list[Decimal]:
    prices: list[Decimal] = []
    for match in _PRICE_TOKEN.finditer(text):
        price = parse_money(match.group())
        if price is not None:
            prices.append(price)
    return prices


def split_trailing_prices(line: str) -> tuple[str, list[Decimal]]:
    prices = extract_prices(line)
    if not prices:
        return line.strip(), []
    cut = line
    for match in reversed(list(_PRICE_TOKEN.finditer(line))):
        cut = cut[:match.start()].rstrip()
        if cut and not _PRICE_TOKEN.search(cut[-15:]):
            break
    return cut.strip(), prices[-3:]
