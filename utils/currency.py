"""Валюта и конвертация в KZT (ТЗ 4.4: «валюта не KZT → конвертировать по курсу
на дату прайса, сохранить оригинал»).

Курсы плоские по умолчанию (для MVP). В проде подставляется таблица курсов
НБ РК на дату прайса — точка расширения через параметр ``rates``.
"""
from __future__ import annotations

from decimal import Decimal

# Курс к KZT. KZT=1 по определению. Значения — ориентир для MVP.
DEFAULT_RATES: dict[str, Decimal] = {
    "KZT": Decimal("1"),
    "USD": Decimal("470"),
    "RUB": Decimal("5.2"),
}

# Маркеры валюты в тексте заголовка/ячейки. Порядок важен: более специфичные выше.
_CURRENCY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("USD", ("$", "usd", "долл", "dollar")),
    ("RUB", ("₽", "rub", "руб", "rur", "ruble")),
    ("KZT", ("₸", "kzt", "тенге", " тг")),
)


def detect_currency(*texts: object) -> str | None:
    """Угадать валюту по тексту заголовков/ячеек. None — если маркеров нет."""
    blob = " ".join(str(t) for t in texts if t is not None).lower()
    for code, markers in _CURRENCY_MARKERS:
        if any(marker in blob for marker in markers):
            return code
    return None


def rate_for(currency: str | None, rates: dict[str, Decimal] | None = None) -> Decimal | None:
    rates = rates or DEFAULT_RATES
    if not currency:
        return None
    return rates.get(currency.upper())


def to_kzt(amount: object, currency: str | None, rates: dict[str, Decimal] | None = None) -> Decimal | None:
    """Сконвертировать сумму в KZT по курсу валюты. None, если нет суммы/курса."""
    if amount is None:
        return None
    rate = rate_for(currency or "KZT", rates)
    if rate is None or rate <= 0:
        return None
    return (Decimal(str(amount)) * rate).quantize(Decimal("0.01"))


def convert_item_to_kzt(item, rates: dict[str, Decimal] | None = None) -> bool:
    """Привести цены позиции к KZT, сохранив оригинал (ТЗ 4.4).

    Оригинальная сумма уходит в ``price_original`` (если ещё не заполнена),
    ``currency_original`` остаётся исходной валютой, а ``price_resident_kzt`` /
    ``price_nonresident_kzt`` пересчитываются в тенге. Возвращает True, если
    конверсия выполнена (валюта была не KZT и курс известен).
    """
    currency = (item.currency_original or "KZT").upper()
    if currency == "KZT":
        return False
    rate = rate_for(currency, rates)
    if rate is None or rate <= 0:
        return False
    # Сохраняем оригинал: берём резидентскую цену в исходной валюте как представителя.
    if item.price_original is None:
        item.price_original = item.price_resident_kzt or item.price_nonresident_kzt
    item.price_resident_kzt = to_kzt(item.price_resident_kzt, currency, rates)
    item.price_nonresident_kzt = to_kzt(item.price_nonresident_kzt, currency, rates)
    return True


def apply_currency_conversion(items, rates: dict[str, Decimal] | None = None) -> list[str]:
    """Конвертировать все позиции не-KZT в тенге. Возвращает предупреждения для лога."""
    warnings: list[str] = []
    for item in items:
        original_currency = (item.currency_original or "KZT").upper()
        if convert_item_to_kzt(item, rates):
            warnings.append(f"converted {original_currency}->KZT: {item.service_name_raw}")
    return warnings
