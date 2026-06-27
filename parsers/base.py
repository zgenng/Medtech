from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from config import ParserConfig
from models import Partner, PriceDocument, ParseResult
from utils.files import guess_effective_date, guess_partner_name


class BaseParser(ABC):
    file_format = "unknown"

    def __init__(self, config: ParserConfig | None = None):
        self.config = config or ParserConfig()

    @abstractmethod
    def parse(self, path: Path, partner: Partner | None = None) -> ParseResult:
        raise NotImplementedError

    def make_partner(self, path: Path, partner: Partner | None) -> Partner:
        return partner or Partner(name=guess_partner_name(path.name))

    def make_document(self, path: Path, partner: Partner) -> PriceDocument:
        return PriceDocument(
            partner_id=partner.partner_id,
            file_name=path.name,
            file_format=self.file_format,
            effective_date=guess_effective_date(path.name),
            parse_status="processing",
        )
