from pathlib import Path

from normalizer import ServiceCatalog, ServiceMatcher
from parsers.factory import ParserFactory

ROOT = Path(__file__).resolve().parent

catalog = ServiceCatalog.from_xlsx(
    ROOT / "data" / "Справочник услуг.xlsx"
)

matcher = ServiceMatcher(
    catalog,
    auto_threshold=0.78,
    review_threshold=0.55,
)

# CHANGE THIS
price_path = ROOT / "data" / "Клиника 8 2026.xlsx"

parser = ParserFactory().for_path(price_path)

result = parser.parse(price_path)

normalized_items, report = matcher.normalize_items(result.items)

print("=" * 60)
print("TOTAL:", report.total)
print("AUTO:", report.auto_matched)
print("REVIEW:", report.needs_review)
print("UNMATCHED:", report.unmatched)
print("AUTO RATE:", report.auto_rate)
print("=" * 60)

for item in normalized_items[:20]:
    print(
        item.original.service_name_raw,
        "->",
        item.service_id,
        item.status,
        item.score,
    )
import csv

with open("review_queue.csv", "w", newline="", encoding="utf-8") as file:
    writer = csv.writer(file)
    writer.writerow([
        "raw_name",
        "service_id",
        "match_status",
        "match_confidence",
        "verification_note",
    ])

    for item in result.items:
        writer.writerow([
            item.service_name_raw,
            item.service_id,
            item.match_status,
            item.match_confidence,
            item.verification_note,
        ])