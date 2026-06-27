from __future__ import annotations

from pathlib import Path

import fitz
import pytesseract
from PIL import Image

from models import Partner, ParseResult
from parsers.base import BaseParser
from parsers.pdf_lines import parse_pdf_lines


class OcrPdfParser(BaseParser):
    file_format = "scan_pdf"

    def parse(self, path: Path, partner: Partner | None = None) -> ParseResult:
        partner = self.make_partner(path, partner)
        document = self.make_document(path, partner)
        result = ParseResult(document=document)
        lines = self._ocr_lines(path, result)
        result.document.raw_content = "\n".join(lines[:3000])
        result.items = parse_pdf_lines(lines, document)
        if not result.items and not result.errors:
            result.errors.append("OCR PDF has no recognized price rows")
        return result.finalize()

    def _ocr_lines(self, path: Path, result: ParseResult) -> list[str]:
        try:
            return self._render_and_ocr(path)
        except Exception as error:
            result.errors.append(f"OCR error: {error}")
            return []

    def _render_and_ocr(self, path: Path) -> list[str]:
        lines: list[str] = []
        with fitz.open(path) as doc:
            for page_number, page in enumerate(doc):
                if self._stop_ocr(page_number):
                    break
                image = self._page_to_image(page)
                text = pytesseract.image_to_string(image, lang="rus+eng")
                lines.extend(text.splitlines())
        return lines

    def _stop_ocr(self, page_number: int) -> bool:
        return self.config.max_ocr_pages is not None and page_number >= self.config.max_ocr_pages

    def _page_to_image(self, page) -> Image.Image:
        zoom = self.config.ocr_dpi / 72
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
