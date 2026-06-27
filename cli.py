from __future__ import annotations

import argparse
from pathlib import Path

from archive_parser import ArchiveParser
from config import ParserConfig
from output_writer import OutputWriter


def main() -> None:
    args = _parse_args()
    config = ParserConfig(parse_scan_pdf=not args.no_ocr)
    payload = ArchiveParser(config).parse(args.archive)
    OutputWriter(args.out).write_all(**payload)
    _print_report(payload["report"], Path(args.out))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse MedArchive price documents")
    parser.add_argument("--archive", required=True, help="ZIP archive, folder, or single document")
    parser.add_argument("--out", default="parsed_output", help="Output directory")
    parser.add_argument("--no-ocr", action="store_true", help="Disable OCR for scanned PDFs")
    return parser.parse_args()


def _print_report(report: dict, output_dir: Path) -> None:
    print("MedArchive parser finished")
    print(f"Documents: {report['documents_total']}")
    print(f"Items: {report['items_total']}")
    print(f"Output: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
