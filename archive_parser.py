from __future__ import annotations

import tempfile
from pathlib import Path

from config import ParserConfig
from models import Partner, ParseResult
from parsers.factory import ParserFactory
from utils.files import guess_partner_name, list_supported_files, safe_extract_zip
from validation import validate_items


class ArchiveParser:
    def __init__(self, config: ParserConfig | None = None):
        self.config = config or ParserConfig()
        self.factory = ParserFactory(self.config)

    def parse(self, source: str | Path) -> dict:
        source_path = Path(source)
        files = self._prepare_files(source_path)
        results = [self._parse_file(path) for path in files]
        return self._build_payload(results)

    def _prepare_files(self, source: Path) -> list[Path]:
        if source.suffix.lower() == ".zip":
            temp_dir = Path(tempfile.mkdtemp(prefix="medarchive_zip_"))
            return safe_extract_zip(source, temp_dir)
        return list_supported_files(source)

    def _parse_file(self, path: Path) -> ParseResult:
        partner = Partner(name=guess_partner_name(path.name))
        try:
            result = self.factory.for_path(path).parse(path, partner)
        except Exception as error:
            result = self._error_result(path, partner, error)
        result.document.file_path = str(path)
        result.warnings.extend(validate_items(result.items))
        return result.finalize()

    def _build_payload(self, results: list[ParseResult]) -> dict:
        partners = self._partners_from_results(results)
        documents = [result.document for result in results]
        items = [item for result in results for item in result.items]
        return {
            "partners": partners,
            "documents": documents,
            "items": items,
            "report": self._report(results, items),
        }

    @staticmethod
    def _partners_from_results(results: list[ParseResult]) -> list[Partner]:
        seen: dict[str, Partner] = {}
        for result in results:
            name = guess_partner_name(result.document.file_name)
            seen.setdefault(result.document.partner_id, Partner(name=name, partner_id=result.document.partner_id))
        return list(seen.values())

    @staticmethod
    def _report(results: list[ParseResult], items: list) -> dict:
        return {
            "documents_total": len(results),
            "documents_done": sum(1 for r in results if r.document.parse_status == "done"),
            "documents_need_review": sum(1 for r in results if r.document.parse_status == "needs_review"),
            "documents_error": sum(1 for r in results if r.document.parse_status == "error"),
            "items_total": len(items),
        }

    def _error_result(self, path: Path, partner: Partner, error: Exception) -> ParseResult:
        document = self.factory.for_path(path).make_document(path, partner)
        document.file_path = str(path)
        result = ParseResult(document=document)
        result.errors.append(str(error))
        return result.finalize()
