from __future__ import annotations

from pathlib import Path

import pdfplumber

from models import Partner, ParseResult
from parsers.base import BaseParser
from parsers.pdf_lines import parse_pdf_lines


class PdfTextParser(BaseParser):
    file_format = "pdf"

    def parse(self, path: Path, partner: Partner | None = None) -> ParseResult:
        partner = self.make_partner(path, partner)
        document = self.make_document(path, partner)
        result = ParseResult(document=document)
        lines = self._extract_lines(path, result)
        result.document.raw_content = "\n".join(lines[:3000])
        result.items = parse_pdf_lines(lines, document)
        if not result.items:
            result.errors.append("PDF has no recognized price rows")
        return result.finalize()

    def has_enough_text(self, path: Path) -> bool:
        lines = self._extract_lines(path, ParseResult(self.make_document(path, Partner("probe"))), max_pages=2)
        return len(" ".join(lines).strip()) >= self.config.min_pdf_text_chars

    @staticmethod
    def _extract_lines(path: Path, result: ParseResult, max_pages: int | None = None) -> list[str]:
        lines: list[str] = []
        try:
            with pdfplumber.open(path) as pdf:
                pages = pdf.pages[:max_pages] if max_pages else pdf.pages
                for page in pages:
                    text = page.extract_text() or ""
                    lines.extend(text.splitlines())
        except Exception as error:
            result.errors.append(f"pdfplumber error: {error}")
        return lines
