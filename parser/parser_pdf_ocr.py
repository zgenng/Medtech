from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import tempfile
import traceback
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import unicodedata
from difflib import SequenceMatcher

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

try:
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None

try:
    from PIL import Image, ImageFilter, ImageOps
except Exception:  # pragma: no cover
    Image = None
    ImageFilter = None
    ImageOps = None

try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls"}
PDF_TEXT_MIN_CHARS_PER_PAGE = 30

YEAR_RE = re.compile(r"(20\d{2})")
MONEY_RE = re.compile(
    r"(?<![\w])(?:\d{1,3}(?:[\s\u00A0]\d{3})+|\d{4,9}|\d{1,3}(?:[.,]\d{1,2})?)(?![\w])",
    re.IGNORECASE,
)


@dataclass
class FileJob:
    job_id: int
    file_name: str
    file_path: str
    file_format: str
    parser_owner: str
    status: str = "pending"  # pending / processing / done / error / skipped / needs_review
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    items_count: int = 0
    pages_count: Optional[int] = None
    parse_log: list[str] = field(default_factory=list)

    def log(self, msg: str) -> None:
        self.parse_log.append(msg)


# -----------------------------------------------------------------------------
# General utilities
# -----------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def normalize_ocr_number(s: str) -> str:
    """Fix common OCR mistakes only for numeric extraction, not for service names."""
    table = str.maketrans(
        {
            "О": "0", "о": "0", "O": "0", "o": "0",
            "С": "0", "с": "0", "C": "0", "c": "0",
            "I": "1", "l": "1", "|": "1",
            "З": "3", "з": "3",
            "Б": "6", "б": "6",
        }
    )
    return s.translate(table)


def money_to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if result > 0 else None

    raw = clean_cell(value)
    if not raw:
        return None

    raw = normalize_ocr_number(raw)
    raw = raw.lower()
    raw = raw.replace("тенге", "").replace("тг", "").replace("kzt", "")
    raw = raw.replace(" ", "").replace("\xa0", "").replace(",", ".")

    m = re.search(r"\d+(?:\.\d+)?", raw)
    if not m:
        return None
    try:
        result = float(m.group(0))
    except ValueError:
        return None
    return result if result > 0 else None


def extract_money_values(text: Any) -> list[float]:
    s = clean_cell(text)
    if not s:
        return []

    values: list[float] = []
    s_num = normalize_ocr_number(s)
    for m in MONEY_RE.finditer(s_num):
        number = money_to_float(m.group(0))
        if number is None:
            continue
        # remove common false positives: years, row indexes, tiny quantities
        if number < 100:
            continue
        if int(number) in {2024, 2025, 2026, 2027, 2028}:
            continue
        values.append(number)
    return values


def partner_from_filename(path: Path) -> str:
    name = path.stem
    name = re.sub(r"(?i)\bпрайс\b", "", name)
    name = re.sub(r"\b20\d{2}\b", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip(" _-") or path.stem


def effective_date_from_filename(path: Path) -> Optional[str]:
    m = YEAR_RE.search(path.name)
    if not m:
        return None
    return f"{m.group(1)}-01-01"


def detect_file_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return detect_pdf_format(path)
    if suffix == ".docx":
        return "docx"
    if suffix in {".xlsx", ".xls"}:
        return suffix.lstrip(".")

    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    return "unknown"


def detect_pdf_format(path: Path) -> str:
    """Return 'pdf' for text PDF and 'scan_pdf' for scanned/image PDF."""
    if fitz is None:
        return "pdf_unknown_no_pymupdf"

    try:
        doc = fitz.open(path)
        if len(doc) == 0:
            return "scan_pdf"
        text_chars = 0
        sample_pages = min(3, len(doc))
        for i in range(sample_pages):
            text_chars += len(clean_cell(doc[i].get_text("text")))
        avg_chars = text_chars / max(sample_pages, 1)
        return "pdf" if avg_chars >= PDF_TEXT_MIN_CHARS_PER_PAGE else "scan_pdf"
    except Exception:
        return "pdf_unknown_error"


def safe_extract_zip(zip_path: Path, out_dir: Path) -> None:
    """Avoid zip-slip vulnerability by checking resolved output path."""
    with zipfile.ZipFile(zip_path, "r") as z:
        for member in z.infolist():
            if member.is_dir():
                continue
            target = out_dir / member.filename
            target_resolved = target.resolve()
            if not str(target_resolved).startswith(str(out_dir.resolve())):
                raise RuntimeError(f"Unsafe ZIP path: {member.filename}")
            z.extract(member, out_dir)


def build_queue(root_dir: Path) -> list[FileJob]:
    files = [
        p for p in root_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    jobs: list[FileJob] = []
    for idx, path in enumerate(sorted(files), start=1):
        fmt = detect_file_format(path)
        if fmt in {"pdf", "scan_pdf", "pdf_unknown_error", "pdf_unknown_no_pymupdf"}:
            owner = "person_2_pdf_ocr"
        elif fmt in {"docx", "xlsx", "xls"}:
            owner = "person_3_xlsx_docx"
        else:
            owner = "unknown"

        jobs.append(
            FileJob(
                job_id=idx,
                file_name=path.name,
                file_path=str(path),
                file_format=fmt,
                parser_owner=owner,
            )
        )
    return jobs


# -----------------------------------------------------------------------------
# PDF extraction
# -----------------------------------------------------------------------------

def parse_pdf_text(path: Path, job: Optional[FileJob] = None) -> list[dict[str, Any]]:
    """Parse a text PDF. Prefer tables from pdfplumber, then fallback to PyMuPDF text blocks."""
    if fitz is None:
        raise RuntimeError("PyMuPDF is not installed. Install: pip install pymupdf")

    partner = partner_from_filename(path)
    effective_date = effective_date_from_filename(path)
    all_items: list[dict[str, Any]] = []

    # 1) Try pdfplumber tables first because medical prices are usually tabular.
    if pdfplumber is not None:
        try:
            with pdfplumber.open(path) as pdf:
                if job:
                    job.pages_count = len(pdf.pages)
                for page_number, page in enumerate(pdf.pages, start=1):
                    tables = page.extract_tables() or []
                    for table_index, table in enumerate(tables):
                        for row in table:
                            item = row_to_price_item(
                                row,
                                partner_name=partner,
                                source_file=path.name,
                                file_format="pdf",
                                effective_date=effective_date,
                                source_page=page_number,
                                extraction_method=f"pdfplumber_table_{table_index}",
                            )
                            if item:
                                all_items.append(item)
            if all_items:
                if job:
                    job.log(f"pdfplumber extracted {len(all_items)} items")
                return all_items
        except Exception as e:
            if job:
                job.log(f"pdfplumber failed: {e}")

    # 2) Fallback to PyMuPDF blocks.
    doc = fitz.open(path)
    if job:
        job.pages_count = len(doc)

    for page_number, page in enumerate(doc, start=1):
        blocks = page.get_text("blocks") or []
        for block in blocks:
            block_text = clean_cell(block[4] if len(block) > 4 else "")
            if not block_text:
                continue
            for row in split_pdf_block_to_rows(block_text):
                item = row_to_price_item(
                    row,
                    partner_name=partner,
                    source_file=path.name,
                    file_format="pdf",
                    effective_date=effective_date,
                    source_page=page_number,
                    extraction_method="pymupdf_blocks",
                )
                if item:
                    all_items.append(item)

    if job:
        job.log(f"PyMuPDF extracted {len(all_items)} items")
    return all_items


def parse_pdf_scan_ocr(
    path: Path,
    job: Optional[FileJob] = None,
    *,
    dpi: int = 250,
    tesseract_lang: str = "rus+eng",
    max_pages: Optional[int] = None,
) -> list[dict[str, Any]]:
    """OCR fallback for scanned PDFs. Requires tesseract binary and pytesseract."""
    if fitz is None:
        raise RuntimeError("PyMuPDF is not installed. Install: pip install pymupdf")
    if pytesseract is None or Image is None:
        raise RuntimeError("OCR dependencies are missing. Install: pip install pytesseract pillow")

    partner = partner_from_filename(path)
    effective_date = effective_date_from_filename(path)
    all_items: list[dict[str, Any]] = []

    doc = fitz.open(path)
    total_pages = len(doc)
    if job:
        job.pages_count = total_pages

    pages_to_process = total_pages if max_pages is None else min(max_pages, total_pages)
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    for page_index in range(pages_to_process):
        page = doc[page_index]
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        image = preprocess_for_ocr(image)

        text = pytesseract.image_to_string(
            image,
            lang=tesseract_lang,
            config="--oem 3 --psm 6",
        )
        lines = [clean_cell(line) for line in text.splitlines()]
        lines = [line for line in lines if line]

        for line in lines:
            for row in split_ocr_line_to_rows(line):
                item = row_to_price_item(
                    row,
                    partner_name=partner,
                    source_file=path.name,
                    file_format="scan_pdf",
                    effective_date=effective_date,
                    source_page=page_index + 1,
                    extraction_method="tesseract_ocr",
                )
                if item:
                    all_items.append(item)

    if job:
        job.log(f"OCR extracted {len(all_items)} items from {pages_to_process}/{total_pages} pages")
    return all_items


def preprocess_for_ocr(image: "Image.Image") -> "Image.Image":
    """Simple OCR preprocessing. Works without OpenCV."""
    if ImageOps is None or ImageFilter is None:
        return image
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    gray = gray.filter(ImageFilter.SHARPEN)
    # light thresholding improves table scans in many cases
    bw = gray.point(lambda x: 255 if x > 170 else 0)
    return bw


# -----------------------------------------------------------------------------
# Row parsing heuristics
# -----------------------------------------------------------------------------

def split_pdf_block_to_rows(text: str) -> list[list[str]]:
    """
    PyMuPDF blocks sometimes contain multiple table rows.
    This function returns row-like cell lists.
    """
    text = text.replace("\t", " | ")
    text = re.sub(r" {2,}", " | ", text)

    # If the block still has real newlines, treat each line as one possible row.
    lines = [clean_cell(line) for line in re.split(r"\n+", text) if clean_cell(line)]
    if len(lines) > 1:
        rows: list[list[str]] = []
        for line in lines:
            rows.extend(split_ocr_line_to_rows(line))
        return rows

    # If no newlines, split by pipes and attempt to identify repeated row starts.
    tokens = [clean_cell(x) for x in text.split("|")]
    tokens = [x for x in tokens if x]
    if not tokens:
        return []

    starts: list[int] = []
    for i, token in enumerate(tokens):
        if i + 1 >= len(tokens):
            continue
        is_row_number = re.fullmatch(r"\d{1,5}", token) is not None
        is_service_code = looks_like_code(token) and not extract_money_values(token)
        next_has_letters = any(
            re.search(r"[A-Za-zА-Яа-я]", tokens[j])
            for j in range(i + 1, min(i + 4, len(tokens)))
        )
        if (is_row_number or is_service_code) and next_has_letters:
            starts.append(i)

    if len(starts) <= 1:
        return [tokens]

    rows: list[list[str]] = []
    for start, end in zip(starts, starts[1:] + [len(tokens)]):
        rows.append(tokens[start:end])
    return rows


def split_ocr_line_to_rows(line: str) -> list[list[str]]:
    """Turn one OCR/text line into a list of cells."""
    line = clean_cell(line)
    if not line:
        return []

    # Table separators and long spaces usually separate columns.
    normalized = line.replace("\t", " | ")
    normalized = re.sub(r"\s{2,}", " | ", normalized)
    normalized = re.sub(r"\s*[|;]+\s*", " | ", normalized)

    cells = [clean_cell(x) for x in normalized.split("|")]
    cells = [c for c in cells if c]

    if len(cells) >= 2:
        return [cells]

    # Fallback: separate service name and price from a single OCR line.
    prices = list(MONEY_RE.finditer(normalize_ocr_number(line)))
    if not prices:
        return [[line]]

    first_price = prices[0]
    service_part = line[: first_price.start()].strip(" .,-—–:")
    price_part = line[first_price.start():].strip()
    if service_part:
        return [[service_part, price_part]]
    return [[line]]


def looks_like_header_or_section(text: str) -> bool:
    t = clean_cell(text).lower()
    if len(t) < 3:
        return True
    bad_words = [
        "наименование услуг", "наименование услуги", "наименование",
        "прейскурант", "прайс", "стоимость", "цена для",
        "цены для", "единица измерения", "ед.изм", "№ п/п",
        "раздел", "подраздел", "утверждаю", "согласовано",
        "медицинских услуг", "тенге", "kzt",
    ]
    if any(w in t for w in bad_words) and not extract_money_values(text):
        return True
    return False


def looks_like_code(text: str) -> bool:
    s = clean_cell(text)
    if not s or len(s) > 30:
        return False
    patterns = [
        r"^[A-ZА-Я]{1,8}\s?\d[\w.\-/]*$",
        r"^[A-ZА-Я]\d{2}\.\d{3}\.\d{3}.*$",
        r"^\d{1,5}(?:\.\d+)*$",
    ]
    return any(re.match(p, s, re.I) for p in patterns)


def looks_like_unit(text: str) -> bool:
    t = clean_cell(text).lower()
    units = {
        "услуга", "прием", "приём", "посещение", "исследование", "анализ",
        "процедура", "операция", "манипуляция", "койко-день", "пакет",
        "час", "день", "сеанс", "шт", "ед", "1 услуга",
    }
    return t in units


def remove_price_fragments(text: str) -> str:
    s = clean_cell(text)
    s = re.sub(r"\b\d{1,3}(?:[\s\u00A0]\d{3})+\b", " ", s)
    s = re.sub(r"\b\d{4,9}\b", " ", s)
    s = re.sub(r"\b(?:тг|тенге|kzt)\b", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" |,-—–:")


def choose_service_name(cells: list[str]) -> tuple[Optional[int], Optional[str]]:
    candidates: list[tuple[int, str]] = []
    for idx, cell in enumerate(cells):
        c = remove_price_fragments(cell)
        if not c:
            continue
        if looks_like_header_or_section(c):
            continue
        if looks_like_code(c):
            continue
        if looks_like_unit(c):
            continue
        if not re.search(r"[A-Za-zА-Яа-я]", c):
            continue
        if len(c) < 4:
            continue
        candidates.append((idx, c))

    if not candidates:
        return None, None
    idx, name = max(candidates, key=lambda item: len(item[1]))
    return idx, re.sub(r"\s+", " ", name).strip()


def normalize_prices(prices: list[float]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    unique: list[float] = []
    for price in prices:
        if price not in unique:
            unique.append(price)
    if not unique:
        return None, None, None
    if len(unique) == 1:
        return unique[0], None, unique[0]
    if len(unique) == 2:
        return unique[0], unique[1], unique[0]
    return unique[0], unique[-1], unique[0]


def row_to_price_item(
    cells_raw: list[Any],
    *,
    partner_name: str,
    source_file: str,
    file_format: str,
    effective_date: Optional[str],
    source_page: Optional[int] = None,
    extraction_method: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    cells = [clean_cell(c) for c in cells_raw]
    cells = [c for c in cells if c]
    if not cells:
        return None

    joined = " | ".join(cells)
    if looks_like_header_or_section(joined):
        return None

    service_idx, service_name = choose_service_name(cells)
    if service_idx is None or not service_name:
        return None

    code = None
    for c in cells[:service_idx]:
        if looks_like_code(c) and not c.isdigit():
            code = c
            break

    # Common case: code and name are in one cell, e.g. "U1.1 Consultation ..."
    if code is None:
        m = re.match(
            r"^([A-ZА-Я]{1,8}\s?\d[\w.\-/]*|\d{1,5}(?:\.\d+)*)\s+(.+)$",
            service_name,
            flags=re.I,
        )
        if m:
            code = m.group(1).strip()
            service_name = m.group(2).strip()

    prices: list[float] = []
    for c in cells[service_idx + 1:]:
        prices.extend(extract_money_values(c))
    if not prices:
        prices = extract_money_values(joined)
    prices = [p for p in prices if p >= 100 and int(p) not in {2024, 2025, 2026, 2027, 2028}]
    if not prices:
        return None

    resident, nonresident, original = normalize_prices(prices)

    return {
        "partner_name": partner_name,
        "source_file": source_file,
        "file_format": file_format,
        "source_sheet": None,
        "source_page": source_page,
        "effective_date": effective_date,
        "service_code_source": code,
        "service_name_raw": service_name,
        "service_id": None,
        "price_resident_kzt": resident,
        "price_nonresident_kzt": nonresident,
        "price_original": original,
        "currency_original": "KZT",
        "is_verified": False,
        "verification_note": None,
        "is_active": True,
        "parse_status": "done",
        "parse_log": None,
        "extraction_method": extraction_method,
    }

# -----------------------------------------------------------------------------
# Person 4: Medical service normalization and matching
# -----------------------------------------------------------------------------

AUTO_MATCH_THRESHOLD = 97
REVIEW_MATCH_THRESHOLD = 85
TOP_CANDIDATES_LIMIT = 5


CONSULTATION_WORDS = {"прием", "приём", "консультация", "осмотр"}
ECG_WORDS = {"экг", "холтер", "смад", "мониторирование", "электрокардиография"}
ULTRASOUND_WORDS = {"узи", "эхокардиография", "эхокг"}
REMOVAL_WORDS = {"удаление", "иссечение"}
WASH_WORDS = {"промывание", "орошение", "вливание", "смазывание", "туалет"}
ENDOSCOPY_WORDS = {"эндоскопия", "эндоскопическое"}
LAB_WORDS = {"забор", "мазок", "соскоб", "анализ", "проба", "кровь", "моча"}
XRAY_WORDS = {"рентген", "кт", "мрт", "томография"}
PUNCTURE_WORDS = {"пункция", "блокада", "катетеризация", "тампонада", "вскрытие"}


GENERIC_QUERIES = {
    "осмотр",
    "консультация",
    "консультация второго",
    "второго консультация",
    "консультация врача",
    "осмотр врача",
}

import unicodedata
from difflib import SequenceMatcher

try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None


@dataclass
class ServiceRef:
    service_id: str
    service_name: str
    specialty: Optional[str] = None
    code: Optional[str] = None
    tarificator_code: Optional[str] = None
    synonyms: list[str] = field(default_factory=list)
    is_active: bool = True


@dataclass
class MatchCandidate:
    service_id: str
    service_name: str
    specialty: Optional[str]
    code: Optional[str]
    tarificator_code: Optional[str]
    score: float
    match_type: str
    matched_by: str


@dataclass
class MatchResult:
    status: str
    service_id: Optional[str]
    confidence: float
    match_type: str
    cleaned_query: str
    normalized_query: str
    candidates: list[MatchCandidate] = field(default_factory=list)


BAD_SERVICE_PATTERNS = [
    r"прилож\s*ение",
    r"договор",
    r"утверждаю",
    r"директор",
    r"страница",
    r"прейскурант",
    r"прайс",
    r"медицинских услуг",
    r"оказание медицинских услуг",
    r"к договору",
]


MEDICAL_REPLACEMENTS = {
    "прием": "консультация",
    "приём": "консультация",
    "консультативный": "консультация",
    "врача": "",
    "врач": "",

    "акушер гинеколога": "акушер гинеколог",
    "акушер-гинеколога": "акушер гинеколог",
    "аллерголога": "аллерголог",
    "дерматовенеролога": "дерматолог",
    "дерматолога": "дерматолог",
    "кардиолога": "кардиолог",
    "трихолога": "трихолог",
    "оториноларинголога": "лор",
    "отоларинголога": "лор",
    "лора": "лор",

    "ультразвуковое исследование": "узи",
    "ультра звуковое исследование": "узи",
    "эхокардиография": "узи сердца",
    "экг": "электрокардиография",
    "холтер": "холтеровское мониторирование экг",
    "суточное мониторирование экг": "холтеровское мониторирование экг",
    "смад": "суточное мониторирование ад",
    "дмад": "суточное мониторирование ад",

    "к.м.н.": "кандидат медицинских наук",
    "д.м.н.": "доктор медицинских наук",
}


def is_bad_service_name(value: Any) -> bool:
    s = clean_cell(value).lower()
    if not s:
        return True
    if len(s) < 3:
        return True
    if not re.search(r"[а-яa-z]", s):
        return True

    compact = re.sub(r"\s+", "", s)
    if "приложение" in compact:
        return True

    for pattern in BAD_SERVICE_PATTERNS:
        if re.search(pattern, s, flags=re.I):
            return True

    return False


def clean_medical_service_name(value: Any) -> str:
    if value is None:
        return ""

    s = str(value)
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\xa0", " ")
    s = s.replace("ё", "е")
    s = re.sub(r"[•·'\"“”«»]+", " ", s)
    s = re.sub(r"\.{2,}", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" ,;:.-—–")

    if is_bad_service_name(s):
        return ""

    s = re.sub(r"^\d+(\s+\d+)*\s+", "", s)
    s = re.sub(r"^[A-ZА-Я]{1,8}\s?\d[\w.\-/]*\s+", "", s, flags=re.I)

    s = re.sub(r"\b\d{1,3}(?:[\s\xa0]\d{3})+\b", " ", s)
    s = re.sub(r"\b\d{4,9}\b", " ", s)
    s = re.sub(r"\b(?:тг|тенге|kzt|руб|rub|usd)\b", " ", s, flags=re.I)
    s = re.sub(r"\s+[иi]\s+\d{3,6}$", "", s, flags=re.I)

    s = re.sub(r"\s+", " ", s)
    return s.strip(" ,;:.-—–")


def normalize_service_text(value: Any) -> str:
    s = clean_medical_service_name(value).lower()
    if not s:
        return ""

    for old, new in sorted(MEDICAL_REPLACEMENTS.items(), key=lambda x: len(x[0]), reverse=True):
        s = s.replace(old, new)

    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-zа-я0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s)

    stop_words = {
        "услуга", "услуги", "медицинская", "медицинские",
        "стоимость", "цена", "платная", "платные",
        "для", "по", "на", "и", "или", "с", "без",
        "один", "одна", "одно", "процедура", "штука", "шт",
        "материала", "средств", "лекарственных",
    }

    tokens = [t for t in s.strip().split() if t not in stop_words]
    tokens = sorted(set(tokens))
    return " ".join(tokens)


def safe_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if fuzz is not None:
        return float(fuzz.WRatio(a, b))
    return SequenceMatcher(None, a, b).ratio() * 100


def service_type(text: Any) -> str:
    n = normalize_service_text(text)
    tokens = set(n.split())

    if tokens & ECG_WORDS:
        return "ecg"
    if tokens & ULTRASOUND_WORDS:
        return "ultrasound"
    if tokens & REMOVAL_WORDS:
        return "removal"
    if tokens & ENDOSCOPY_WORDS:
        return "endoscopy"
    if tokens & WASH_WORDS:
        return "wash"
    if tokens & PUNCTURE_WORDS:
        return "puncture"
    if tokens & LAB_WORDS:
        return "lab"
    if tokens & XRAY_WORDS:
        return "imaging"
    if tokens & CONSULTATION_WORDS:
        return "consultation"

    return "other"


def is_generic_query(query: str) -> bool:
    q = clean_cell(query).lower()
    tokens = q.split()

    if q in GENERIC_QUERIES:
        return True

    if len(tokens) <= 1:
        return True

    if len(tokens) == 2 and ("консультация" in tokens or "осмотр" in tokens):
        return True

    return False


def token_overlap(a: str, b: str) -> float:
    a_tokens = set(a.split())
    b_tokens = set(b.split())

    if not a_tokens or not b_tokens:
        return 0.0

    return len(a_tokens & b_tokens) / max(len(a_tokens), len(b_tokens))


def has_strong_medical_overlap(a: str, b: str) -> bool:
    overlap = token_overlap(a, b)
    if overlap >= 0.5:
        return True

    a_tokens = set(a.split())
    b_tokens = set(b.split())

    important = (
        ECG_WORDS
        | ULTRASOUND_WORDS
        | REMOVAL_WORDS
        | WASH_WORDS
        | ENDOSCOPY_WORDS
        | LAB_WORDS
        | XRAY_WORDS
        | PUNCTURE_WORDS
    )

    return bool((a_tokens & b_tokens) & important)

class ServiceMatcher:
    def __init__(
        self,
        services: list[ServiceRef],
        *,
        auto_threshold: int = AUTO_MATCH_THRESHOLD,
        review_threshold: int = REVIEW_MATCH_THRESHOLD,
    ) -> None:
        self.services = [s for s in services if s.is_active]
        self.auto_threshold = auto_threshold
        self.review_threshold = review_threshold
        self.variant_index: dict[str, tuple[ServiceRef, str]] = {}
        self.variants: list[str] = []
        self._build_indexes()

    def _build_indexes(self) -> None:
        self.variant_index.clear()
        self.variants.clear()

        for service in self.services:

            variants = [service.service_name]
            variants.extend(service.synonyms)

            for raw_variant in variants:
                variant = normalize_service_text(raw_variant)

                if not variant:
                    continue

                source_type = (
                    "official"
                    if raw_variant == service.service_name
                    else "generated"
                )

                self.variant_index[variant] = (service, source_type)
                self.variants.append(variant)

        self.variants = sorted(set(self.variants))

    def match(self, raw_name: Any) -> MatchResult:
        cleaned = clean_medical_service_name(raw_name)
        query = normalize_service_text(cleaned)

        if not query:
            return MatchResult(
                status="unmatched",
                service_id=None,
                confidence=0,
                match_type="bad_or_empty",
                cleaned_query=cleaned,
                normalized_query="",
                candidates=[],
            )

        if query in self.variant_index:
            service, source_type = self.variant_index[query]
            candidate = self._candidate(service, 100, f"exact_{source_type}", query)
            return MatchResult(
                status="matched",
                service_id=service.service_id,
                confidence=100,
                match_type=f"exact_{source_type}",
                cleaned_query=cleaned,
                normalized_query=query,
                candidates=[candidate],
            )

        candidates = self._get_candidates(query)

        if not candidates:
            return MatchResult(
                status="unmatched",
                service_id=None,
                confidence=0,
                match_type="no_candidates",
                cleaned_query=cleaned,
                normalized_query=query,
                candidates=[],
            )

        best = candidates[0]

        if best.score >= self.auto_threshold:
            return MatchResult(
                status="matched",
                service_id=best.service_id,
                confidence=best.score,
                match_type=best.match_type,
                cleaned_query=cleaned,
                normalized_query=query,
                candidates=candidates,
            )

        if best.score >= self.review_threshold:
            return MatchResult(
                status="needs_review",
                service_id=None,
                confidence=best.score,
                match_type=best.match_type,
                cleaned_query=cleaned,
                normalized_query=query,
                candidates=candidates,
            )

        return MatchResult(
            status="unmatched",
            service_id=None,
            confidence=best.score,
            match_type=best.match_type,
            cleaned_query=cleaned,
            normalized_query=query,
            candidates=candidates,
        )

    def _get_candidates(self, query: str) -> list[MatchCandidate]:
        scored: list[MatchCandidate] = []

        for variant in self.variants:
            service, source_type = self.variant_index[variant]

            base_score = safe_ratio(query, variant)
            bonus = self._token_bonus(query, variant)
            final_score = min(100.0, base_score + bonus)

            if final_score < self.review_threshold - 12:
                continue

            scored.append(
                self._candidate(
                    service=service,
                    score=round(final_score, 2),
                    match_type=f"fuzzy_{source_type}",
                    matched_by=variant,
                )
            )

        scored.sort(key=lambda x: x.score, reverse=True)

        unique: list[MatchCandidate] = []
        seen: set[str] = set()

        for candidate in scored:
            if candidate.service_id in seen:
                continue
            seen.add(candidate.service_id)
            unique.append(candidate)
            if len(unique) >= TOP_CANDIDATES_LIMIT:
                break

        return unique

    @staticmethod
    def _token_bonus(a: str, b: str) -> float:
        a_tokens = set(a.split())
        b_tokens = set(b.split())
        if not a_tokens or not b_tokens:
            return 0.0

        overlap = len(a_tokens & b_tokens) / max(len(a_tokens), len(b_tokens))

        if overlap >= 0.85:
            return 10.0
        if overlap >= 0.65:
            return 7.0
        if overlap >= 0.45:
            return 4.0
        if overlap >= 0.30:
            return 2.0
        return 0.0

    @staticmethod
    def _candidate(
        service: ServiceRef,
        score: float,
        match_type: str,
        matched_by: str,
    ) -> MatchCandidate:
        return MatchCandidate(
            service_id=service.service_id,
            service_name=service.service_name,
            specialty=service.specialty,
            code=service.code,
            tarificator_code=service.tarificator_code,
            score=round(score, 2),
            match_type=match_type,
            matched_by=matched_by,
        )

def is_ref_broken(value: Any) -> bool:
    return clean_cell(value).upper() in {"#REF!", "#N/A", "#VALUE!", ""}


def is_consultation_service(name: str) -> bool:
    n = clean_cell(name).lower()
    return any(x in n for x in ["прием", "приём", "консультация", "осмотр"])

def load_services_from_xlsx(path: str | Path) -> list[ServiceRef]:
    try:
        import openpyxl
    except Exception:
        raise RuntimeError("openpyxl is not installed. Install: pip install openpyxl")

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    if not rows:
        return []

    header_idx = 0
    for i, row in enumerate(rows[:20]):
        joined = " ".join(clean_cell(c).lower() for c in row)
        if "name_ru" in joined or "специальность" in joined or "tarificatr" in joined:
            header_idx = i
            break

    headers = [clean_cell(x).lower() for x in rows[header_idx]]
    services: list[ServiceRef] = []

    for row in rows[header_idx + 1:]:
        item = {key: value for key, value in zip(headers, row)}

        raw_id = item.get("id")
        specialty = clean_cell(item.get("специальность"))
        code = clean_cell(item.get("code"))
        name_ru = clean_cell(item.get("name_ru"))
        tarificator = (
            item.get("tarificatrсode")
            or item.get("tarificatorcode")
            or item.get("tarificatrcode")
            or item.get("tarificatr_code")
            or item.get("tarificatr code")
        )

        service_id = clean_cell(raw_id) or code or name_ru

        if not name_ru:
            continue

        if is_ref_broken(service_id) or is_ref_broken(code) or is_ref_broken(name_ru):
            continue

        synonyms = generate_medical_synonyms(name_ru, specialty)

        services.append(
            ServiceRef(
                service_id=service_id,
                service_name=name_ru,
                specialty=specialty or None,
                code=code or None,
                tarificator_code=clean_cell(tarificator) or None,
                synonyms=synonyms,
                is_active=True,
            )
        )

    return services



def load_services_from_json(path: str | Path) -> list[ServiceRef]:
    path = Path(path)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = data.get("services", [])

    services: list[ServiceRef] = []

    for row in data:
        service_name = clean_cell(
            row.get("Name_ru")
            or row.get("name_ru")
            or row.get("service_name")
            or row.get("name")
        )
        specialty = clean_cell(row.get("Специальность") or row.get("specialty"))
        code = clean_cell(row.get("Code") or row.get("code"))
        service_id = clean_cell(row.get("ID") or row.get("id")) or code or service_name
        tarificator = clean_cell(
            row.get("TarificatrCode")
            or row.get("tarificatr_code")
            or row.get("tarificator_code")
        )

        if not service_name:
            continue

        synonyms = row.get("synonyms") or []
        if isinstance(synonyms, str):
            synonyms = re.split(r"[,;|]\s*", synonyms)

        synonyms = [clean_cell(x) for x in synonyms if clean_cell(x)]
        synonyms.extend(generate_medical_synonyms(service_name, specialty))

        services.append(
            ServiceRef(
                service_id=service_id,
                service_name=service_name,
                specialty=specialty or None,
                code=code or None,
                tarificator_code=tarificator or None,
                synonyms=sorted(set(synonyms)),
                is_active=True,
            )
        )

    return services


def load_services(path: str | Path) -> list[ServiceRef]:
    path = Path(path)

    if path.suffix.lower() == ".json":
        return load_services_from_json(path)

    if path.suffix.lower() in {".xlsx", ".xls"}:
        return load_services_from_xlsx(path)

    raise ValueError(f"Unsupported service dictionary format: {path.suffix}")


def generate_medical_synonyms(service_name: str, specialty: str = "") -> list[str]:
    name = clean_cell(service_name)
    spec = clean_cell(specialty)
    result = set()

    if name:
        result.add(name)

    if is_consultation_service(name):
        rest = name
        rest = re.sub(r"(?i)^при[её]м\s+", "", rest).strip()
        rest = re.sub(r"(?i)^консультация\s+", "", rest).strip()
        rest = re.sub(r"(?i)^врача\s+", "", rest).strip()

        result.add(f"прием {rest}")
        result.add(f"приём {rest}")
        result.add(f"прием врача {rest}")
        result.add(f"приём врача {rest}")
        result.add(f"консультация {rest}")
        result.add(f"консультация врача {rest}")

        if spec:
            result.add(f"прием {spec}")
            result.add(f"приём {spec}")
            result.add(f"прием врача {spec}")
            result.add(f"приём врача {spec}")
            result.add(f"консультация {spec}")
            result.add(f"консультация врача {spec}")

    low = name.lower()

    if "эхокардиография" in low or "узи сердца" in low:
        result.add("УЗИ сердца")
        result.add("ЭхоКГ")
        result.add("ЭхоКГ с допплерографией")
        result.add("Эхокардиография с допплерографией")

    if "холтер" in low or "мониторирование экг" in low:
        result.add("Холтер ЭКГ")
        result.add("Суточное мониторирование ЭКГ")
        result.add("Холтеровское мониторирование ЭКГ")

    if "суточное мониторирование ад" in low or "смад" in low:
        result.add("СМАД")
        result.add("Мониторирование АД")
        result.add("Суточное мониторирование артериального давления")

    if "экг" in low or "электрокардиография" in low:
        result.add("ЭКГ")
        result.add("Электрокардиография")

    return sorted(x for x in result if clean_cell(x))


def match_price_items(
    items: list[dict[str, Any]],
    services: list[ServiceRef],
    *,
    auto_threshold: int = AUTO_MATCH_THRESHOLD,
    review_threshold: int = REVIEW_MATCH_THRESHOLD,
) -> dict[str, Any]:
    matcher = ServiceMatcher(
        services,
        auto_threshold=auto_threshold,
        review_threshold=review_threshold,
    )

    matched_items: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    unmatched_items: list[dict[str, Any]] = []

    for item in items:
        result = matcher.match(item.get("service_name_raw"))

        enriched = dict(item)
        enriched["service_name_clean"] = result.cleaned_query
        enriched["normalized_service_name"] = result.normalized_query
        enriched["match_status"] = result.status
        enriched["match_confidence"] = result.confidence
        enriched["match_type"] = result.match_type
        enriched["match_candidates"] = [asdict(c) for c in result.candidates]

        if result.status == "matched":
            enriched["service_id"] = result.service_id
            enriched["is_verified"] = result.confidence >= 95
            enriched["verification_note"] = "auto matched"
            matched_items.append(enriched)

        elif result.status == "needs_review":
            enriched["service_id"] = None
            enriched["is_verified"] = False
            enriched["parse_status"] = "needs_review"
            enriched["verification_note"] = "needs manual confirmation"
            review_items.append(enriched)

        else:
            enriched["service_id"] = None
            enriched["is_verified"] = False
            enriched["parse_status"] = "needs_review"
            enriched["verification_note"] = "unmatched service"
            unmatched_items.append(enriched)

    total = len(items)
    matched_count = len(matched_items)
    review_count = len(review_items)
    unmatched_count = len(unmatched_items)

    summary = {
        "total_items": total,
        "matched_items": matched_count,
        "needs_review_items": review_count,
        "unmatched_items": unmatched_count,
        "auto_match_percent": round((matched_count / total) * 100, 2) if total else 0,
        "review_percent": round((review_count / total) * 100, 2) if total else 0,
        "unmatched_percent": round((unmatched_count / total) * 100, 2) if total else 0,
        "auto_threshold": auto_threshold,
        "review_threshold": review_threshold,
        "services_count": len(services),
        "created_at": now_iso(),
    }

    return {
        "items": matched_items + review_items + unmatched_items,
        "matched": matched_items,
        "needs_review": review_items,
        "unmatched": unmatched_items,
        "summary": summary,
    }


def match_archive_result(
    parser_result: dict[str, Any],
    service_dictionary_path: str | Path,
    *,
    auto_threshold: int = AUTO_MATCH_THRESHOLD,
    review_threshold: int = REVIEW_MATCH_THRESHOLD,
) -> dict[str, Any]:
    services = load_services(service_dictionary_path)
    items = parser_result.get("items", [])

    matching_result = match_price_items(
        items,
        services,
        auto_threshold=auto_threshold,
        review_threshold=review_threshold,
    )

    return {
        "items": matching_result["items"],
        "matched": matching_result["matched"],
        "needs_review": matching_result["needs_review"],
        "unmatched": matching_result["unmatched"],
        "jobs": parser_result.get("jobs", []),
        "parser_summary": parser_result.get("summary", {}),
        "matching_summary": matching_result["summary"],
    }


def save_matching_result(result: dict[str, Any], out_path: str | Path) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

# -----------------------------------------------------------------------------
# Worker orchestration
# -----------------------------------------------------------------------------

def process_pdf_job(job: FileJob, *, enable_ocr: bool = True, ocr_max_pages: Optional[int] = None) -> list[dict[str, Any]]:
    path = Path(job.file_path)
    job.status = "processing"
    job.started_at = now_iso()

    try:
        if job.file_format == "pdf":
            items = parse_pdf_text(path, job)
            # If text extraction returned almost nothing, try OCR fallback.
            if enable_ocr and len(items) == 0:
                job.log("Text PDF parser returned 0 items; trying OCR fallback")
                items = parse_pdf_scan_ocr(path, job, max_pages=ocr_max_pages)
        elif job.file_format in {"scan_pdf", "pdf_unknown_error", "pdf_unknown_no_pymupdf"}:
            if not enable_ocr:
                job.status = "needs_review"
                job.log("Scanned PDF detected, but OCR is disabled")
                return []
            items = parse_pdf_scan_ocr(path, job, max_pages=ocr_max_pages)
        else:
            job.status = "skipped"
            job.log(f"Not a PDF for person 2: {job.file_format}")
            return []

        job.items_count = len(items)
        job.status = "done" if items else "needs_review"
        if not items:
            job.log("No price rows extracted")
        return items

    except Exception as e:
        job.status = "error"
        job.log(str(e))
        job.log(traceback.format_exc(limit=2))
        return []
    finally:
        job.finished_at = now_iso()


def parse_archive_pdf_worker(
    zip_path: str | Path,
    *,
    enable_ocr: bool = True,
    ocr_max_pages: Optional[int] = None,
) -> dict[str, Any]:
    """
    Main function for backend integration.

    Returns:
    {
      "items": [raw PriceItem dicts],
      "jobs": [queue status dicts],
      "summary": {...}
    }
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        safe_extract_zip(zip_path, tmp_dir)
        jobs = build_queue(tmp_dir)

        all_items: list[dict[str, Any]] = []
        for job in jobs:
            if job.parser_owner != "person_2_pdf_ocr":
                job.status = "skipped"
                job.log("Assigned to another worker")
                continue
            items = process_pdf_job(job, enable_ocr=enable_ocr, ocr_max_pages=ocr_max_pages)
            all_items.extend(items)

    summary = {
        "archive_name": zip_path.name,
        "total_files": len(jobs),
        "pdf_jobs": sum(1 for j in jobs if j.parser_owner == "person_2_pdf_ocr"),
        "done": sum(1 for j in jobs if j.status == "done"),
        "needs_review": sum(1 for j in jobs if j.status == "needs_review"),
        "error": sum(1 for j in jobs if j.status == "error"),
        "skipped": sum(1 for j in jobs if j.status == "skipped"),
        "items_count": len(all_items),
        "created_at": now_iso(),
    }

    return {
        "items": all_items,
        "jobs": [asdict(job) for job in jobs],
        "summary": summary,
    }


def main() -> None:
    arg_parser = argparse.ArgumentParser(description="Person 2 PDF/OCR worker for MedArchive")
    arg_parser.add_argument("zip_path", help="Path to ZIP archive")
    arg_parser.add_argument("--out", default="person2_pdf_ocr_result.json", help="Output JSON path")
    arg_parser.add_argument("--services", default=None, help="Path to service dictionary JSON/XLSX")
    arg_parser.add_argument("--no-ocr", action="store_true", help="Disable OCR fallback")
    arg_parser.add_argument("--ocr-max-pages", type=int, default=None, help="Limit OCR pages per scanned PDF for fast demo")
    args = arg_parser.parse_args()

    result = parse_archive_pdf_worker(
        args.zip_path,
        enable_ocr=not args.no_ocr,
        ocr_max_pages=args.ocr_max_pages,
    )
    if args.services:
        result = match_archive_result(result, args.services)


    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if "matching_summary" in result:
        print(json.dumps(result["matching_summary"], ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"Saved result to {args.out}")


if __name__ == "__main__":
    main()
