from pathlib import Path

from normalizer import ServiceCatalog, ServiceMatcher

ROOT = Path(__file__).resolve().parent

catalog_path = ROOT / "data" / "Справочник услуг.xlsx"

catalog = ServiceCatalog.from_xlsx(catalog_path)
matcher = ServiceMatcher(catalog)

tests = [
    "Консультация терапевта",
    "Прием врача терапевта",
    "конс. терапевта",
    "УЗИ брюшной полости",
    "ЭКГ",
    "Общий анализ крови",
]

for text in tests:
    print(text, "=>", matcher.match(text))