from __future__ import annotations

import argparse
from pathlib import Path

from config import ParserConfig
from output_writer import OutputWriter
from pipeline import run


def main() -> None:
    args = _parse_args()
    config = ParserConfig(parse_scan_pdf=not args.no_ocr)
    summary = run(args.archive, config=config, to_db=args.to_db, normalize=args.normalize)

    if not args.to_db:
        # Поведение по умолчанию: выгрузка в JSON/CSV (ничего не ломаем).
        OutputWriter(args.out).write_all(**summary["payload"])

    _print_report(args, summary)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse MedArchive price documents")
    parser.add_argument("--archive", required=True, help="ZIP archive, folder, or single document")
    parser.add_argument("--out", default="parsed_output", help="Output directory (без --to-db)")
    parser.add_argument("--no-ocr", action="store_true", help="Disable OCR for scanned PDFs")
    parser.add_argument("--to-db", action="store_true", help="Записать результат в Supabase")
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="После загрузки прогнать нормализатор по очереди unmatched (нужен --to-db)",
    )
    args = parser.parse_args()
    if args.normalize and not args.to_db:
        parser.error("--normalize требует --to-db (нормализатор читает позиции из БД)")
    return args


def _print_report(args: argparse.Namespace, summary: dict) -> None:
    report = summary["parse_report"]
    print("MedArchive parser finished")
    print(f"Documents: {report['documents_total']}  (errors: {report['documents_error']})")
    print(f"Items parsed: {report['items_total']}")

    if not args.to_db:
        print(f"Output: {Path(args.out).resolve()}")
        return

    save = summary["save_report"]
    print(
        f"Saved to DB: documents={save['documents_saved']} "
        f"(error={save['documents_error']}), items inserted={save['items_inserted']}"
    )
    for err in save["errors"]:
        print(f"  ! {err}")

    stats = summary.get("normalize_stats")
    if stats:
        total = stats["total"] or 1
        auto_pct = 100 * stats["auto"] / total
        print(
            f"Normalized: auto={stats['auto']} review={stats['review']} "
            f"unmatched={stats['unmatched']} (auto {auto_pct:.0f}% of {stats['total']})"
        )


if __name__ == "__main__":
    main()
