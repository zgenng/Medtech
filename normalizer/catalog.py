from __future__ import annotations

import re
import uuid
from pathlib import Path

import pandas as pd

from normalizer.models import ServiceRecord
from normalizer.preprocess import TextPreprocessor
from normalizer.synonyms import SynonymExpander


class ServiceCatalog:
    def __init__(self, services: list[ServiceRecord]):
        self.services = services
        self.preprocessor = TextPreprocessor()
        self.synonyms = SynonymExpander()

        self.by_exact: dict[str, ServiceRecord] = {}
        self.by_code: dict[str, ServiceRecord] = {}
        self.choices: list[str] = []
        self.choice_to_service: dict[str, ServiceRecord] = {}

        self._build_indexes()

    @classmethod
    def from_xlsx(cls, path: str | Path) -> "ServiceCatalog":
        df = pd.read_excel(path)
        services: list[ServiceRecord] = []

        for _, row in df.iterrows():
            name = _pick(row, ["service_name", "Name_ru", "name", "Название"])
            if not name:
                continue

            category = _pick(row, ["category", "Специальность", "Категория"])
            code = _pick(row, ["Code", "code", "service_code"])
            tarificator_code = _pick(row, ["TarificatrCode", "tarificator_code", "Тарификатор"])
            raw_id = _pick(row, ["service_id", "uuid", "ID"])

            service_id = raw_id or str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{name}|{code}|{tarificator_code}"))
            synonyms = _parse_synonyms(_pick(row, ["synonyms", "Синонимы", "aliases"]))

            services.append(
                ServiceRecord(
                    service_id=str(service_id),
                    service_name=str(name).strip(),
                    category=str(category).strip() if category else None,
                    code=str(code).strip() if code else None,
                    tarificator_code=str(tarificator_code).strip() if tarificator_code else None,
                    synonyms=synonyms,
                )
            )

        return cls(services)

    def normalize_name(self, text: object) -> str:
        return self.preprocessor.normalize(text)

    def _build_indexes(self) -> None:
        for service in self.services:
            names = [service.service_name, *service.synonyms]

            for name in names:
                normalized = self.normalize_name(name)

                if not normalized:
                    continue

                service.normalized_names.append(normalized)
                self.by_exact[normalized] = service
                self.choices.append(normalized)
                self.choice_to_service[normalized] = service

            for code in [service.code, service.tarificator_code]:
                if code:
                    self.by_code[str(code).strip().lower()] = service


def _pick(row, names: list[str]) -> str | None:
    for name in names:
        if name in row and pd.notna(row[name]):
            value = str(row[name]).strip()
            if value:
                return value

    return None


def _parse_synonyms(value: str | None) -> list[str]:
    if not value:
        return []

    value = value.strip().strip("[]")
    parts = re.split(r"[;,\n|]+", value)

    return [p.strip().strip('"').strip("'") for p in parts if p.strip()]