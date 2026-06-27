from __future__ import annotations

import os
import re
import shutil
import zipfile
from datetime import date
from pathlib import Path


def decode_zip_name(name: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    return re.sub(r"#U([0-9A-Fa-f]{4})", repl, name)


def safe_extract_zip(zip_path: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            decoded = decode_zip_name(info.filename)
            target = _safe_target(output_dir, decoded)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as dest:
                shutil.copyfileobj(source, dest)
            files.append(target)
    return files


def list_supported_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if is_supported_file(path) else []
    return [p for p in path.rglob("*") if is_supported_file(p)]


def is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in {".pdf", ".docx", ".xlsx", ".xls"}


def guess_effective_date(file_name: str) -> date | None:
    year = _find_year(file_name)
    return date(year, 1, 1) if year else None


def guess_partner_name(file_name: str) -> str:
    stem = Path(file_name).stem
    stem = re.sub(r"\b(прайс|price|год|года|20\d{2})\b", " ", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[_\-]+", " ", stem)
    return re.sub(r"\s+", " ", stem).strip() or Path(file_name).stem


def _safe_target(root: Path, name: str) -> Path:
    safe = Path(name.replace("\\", "/"))
    parts = [part for part in safe.parts if part not in {"", ".", ".."}]
    target = root.joinpath(*parts)
    if os.path.commonpath([root.resolve(), target.resolve().parent]) != str(root.resolve()):
        raise ValueError(f"Unsafe archive member: {name}")
    return target


def _find_year(text: str) -> int | None:
    match = re.search(r"\b(20\d{2})\b", text)
    return int(match.group(1)) if match else None
