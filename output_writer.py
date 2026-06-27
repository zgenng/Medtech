from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from models import Partner, PriceDocument, PriceItem, to_plain_dict


class OutputWriter:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_all(
        self,
        partners: Iterable[Partner],
        documents: Iterable[PriceDocument],
        items: Iterable[PriceItem],
        report: dict,
    ) -> None:
        self.write_json("partners.json", [to_plain_dict(p) for p in partners])
        self.write_json("documents.json", [to_plain_dict(d) for d in documents])
        self.write_csv("price_items.csv", [to_plain_dict(i) for i in items])
        self.write_json("parse_report.json", report)

    def write_json(self, file_name: str, payload) -> None:
        path = self.output_dir / file_name
        with open(path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)

    def write_csv(self, file_name: str, rows: list[dict]) -> None:
        path = self.output_dir / file_name
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with open(path, "w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
