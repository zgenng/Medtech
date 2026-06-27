from __future__ import annotations

from pathlib import Path

from config import ParserConfig
from parsers.base import BaseParser
from parsers.docx_parser import DocxParser
from parsers.ocr_pdf_parser import OcrPdfParser
from parsers.pdf_parser import PdfTextParser
from parsers.xlsx_parser import XlsxParser


class ParserFactory:
    def __init__(self, config: ParserConfig | None = None):
        self.config = config or ParserConfig()

    def for_path(self, path: Path) -> BaseParser:
        suffix = path.suffix.lower()
        if suffix == ".docx":
            return DocxParser(self.config)
        if suffix in {".xlsx", ".xls"}:
            return XlsxParser(self.config)
        if suffix == ".pdf":
            return self._pdf_parser(path)
        raise ValueError(f"Unsupported file type: {path}")

    def _pdf_parser(self, path: Path) -> BaseParser:
        text_parser = PdfTextParser(self.config)
        if text_parser.has_enough_text(path) or not self.config.parse_scan_pdf:
            return text_parser
        return OcrPdfParser(self.config)
