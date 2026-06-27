from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True)
class ParserConfig:
    """Runtime settings for file parsing only. No normalization is used."""

    min_pdf_text_chars: int = 80
    ocr_dpi: int = 220
    max_ocr_pages: int | None = None
    default_currency: str = "KZT"
    parse_scan_pdf: bool = True
    # Курсы валют к KZT для конвертации (ТЗ 4.4). None → utils.currency.DEFAULT_RATES.
    currency_rates: dict[str, Decimal] | None = None
