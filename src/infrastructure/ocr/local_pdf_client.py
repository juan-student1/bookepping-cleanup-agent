"""
Free / local PDF extraction — no LlamaParse, no paid OCR APIs.

Uses pdfplumber first; scanned/image-only PDFs automatically fall back to
Tesseract OCR (pypdfium2 render → pytesseract).
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from src.domain.exceptions import ExtractionError
from src.domain.models.bank_movement import BankMovement
from src.infrastructure.ocr.extraction_result import PdfExtractionResult
from src.infrastructure.ocr.tesseract_client import PDF_TEXT_MIN_CHARS, TesseractOcrClient

logger = logging.getLogger(__name__)

_SKIP_LINES = (
    "BEGINNING BALANCE",
    "ENDING BALANCE",
    "PAGE ",
    "ACCOUNT NUMBER",
    "STATEMENT PERIOD",
    "OPENING BALANCE",
    "CLOSING BALANCE",
    "PREVIOUS BALANCE",
    "NEW BALANCE",
)

# A money amount on a statement line: "$44.00", "-$39.91", "$ 789.76-", "$429.00 CR", "21.66".
_MONEY_RE = re.compile(
    r"(?<![\w.,$-])(?:(?P<lead>-)(?=\$?\d))?(?P<dollar>\$)?\s?(?P<lead2>-)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})(?![\d,])(?P<trail>-(?!\d)|\s?CR\b)?",
    re.I,
)
# Line that opens a transaction: optional card-number column ("8398 11/02 …") then the date.
_DATE_LINE_RE = re.compile(
    r"^[.\s]*(?:\d{4}\s+)?(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\s+(.+)$"
)
_CONTINUATION_LINES = 4  # a wrapped description can push its amount a few lines down


@dataclass(frozen=True)
class LineAmount:
    amount: Decimal
    credit: bool  # printed as a credit: leading/trailing minus or "CR"
    start: int  # where the amount starts in the line


def line_amount(text: str) -> LineAmount | None:
    """The transaction amount on a statement line.

    The first "$" amount wins (a two-column page can append a rewards figure such as "+$6.25"
    after "$44.00", and a foreign-currency line prints "1,395,550.00 COLOMBIAN PESO $347.22");
    without "$", the first decimal amount (the running balance, when printed, comes after it).
    """
    found = list(_MONEY_RE.finditer(text))
    if not found:
        return None
    m = next((f for f in found if f.group("dollar")), found[0])
    value = Decimal(m.group("num").replace(",", ""))
    credit = bool(m.group("lead") or m.group("lead2") or m.group("trail"))
    return LineAmount(amount=value, credit=credit, start=m.start())


_PAYMENT_WORDS = ("AUTOPAY", "DEPOSIT")

# Section headings decide the side of the lines below them (no amount on the heading line).
_CREDIT_SECTION_RE = re.compile(
    r"deposits\s*,?\s*(?:and\s*)?(?:other\s*)?credits|"
    r"payments?\s*[,&]?\s*(?:and\s*)?(?:other\s*)?credits|"
    r"^\s*other\s*credits\b|^\s*payments\s*$",
    re.I,
)
_DEBIT_SECTION_RE = re.compile(
    r"withdrawals|debits\s*and\s*service\s*charges|purchases\s*(?:,|&|and\s*other|balance)|"
    r"standard\s*purchases|^\s*checks\b|interest\s*charged|fees\s*charged",
    re.I,
)
# Side-column text (rewards summaries) that must not complete a wrapped transaction line.
_SIDE_NOTE_RE = re.compile(r"\.{3,}|:\s*\$")


def section_side(line: str) -> str | None:
    """'credit' / 'debit' when the line is a section heading, else None."""
    if _MONEY_RE.search(line):
        return None
    if _CREDIT_SECTION_RE.search(line):
        return "credit"
    if _DEBIT_SECTION_RE.search(line):
        return "debit"
    return None


def is_payment(description: str) -> bool:
    desc_u = description.upper()
    return (
        any(w in desc_u for w in _PAYMENT_WORDS)
        or ("PAYMENT" in desc_u and "THANK" in desc_u)
        or desc_u.startswith("PAYMENT")
    )


def _parse_decimal(raw: str) -> Decimal:
    cleaned = raw.strip().replace(" ", "").replace("$", "").replace("€", "")
    neg = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    if re.match(r"^\d{1,3}(\.\d{3})+(,\d+)?$", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")
    return -value if neg else value


def _normalise_date(raw: str, statement_month: str | None = None) -> date:
    raw = raw.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return date.fromisoformat(raw)

    year_hint = month_hint = None
    if statement_month and re.match(r"^\d{4}-\d{2}$", statement_month):
        year_hint, month_hint = int(statement_month[:4]), int(statement_month[5:7])

    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    m = re.match(r"^(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?$", raw)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if y:
            year = int(y)
            if year < 100:
                year += 2000
        else:
            year = year_hint or date.today().year
        month, day = a, b
        if a > 12 and b <= 12:
            day, month = a, b
        if not y and month_hint and month > month_hint:
            # MM/DD without a year on a statement that closes in January: December is last year.
            year -= 1
        try:
            return date(year, month, day)
        except ValueError:
            if a <= 12:
                return date(year, a, min(b, 28))
            raise
    raise ValueError(f"unparseable date: {raw}")


class LocalPdfClient:
    """$0 PDF text + bank-line extraction (pdfplumber → Tesseract fallback)."""

    def __init__(self, ocr: TesseractOcrClient | None = None) -> None:
        self._ocr = ocr or TesseractOcrClient()
        self.last_extraction_engine: str = "pdfplumber"

    def _extract_pdfplumber_text(self, file_path: Path) -> tuple[str, int]:
        if not file_path.exists():
            raise ExtractionError(f"PDF not found: {file_path}")
        chunks: list[str] = []
        page_count = 0
        try:
            with pdfplumber.open(str(file_path)) as pdf:
                page_count = len(pdf.pages)
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    if text.strip():
                        chunks.append(text)
                    for table in page.extract_tables() or []:
                        for row in table:
                            cells = [str(c).strip() if c else "" for c in row]
                            if any(cells):
                                chunks.append(" | ".join(cells))
        except Exception as exc:
            raise ExtractionError(f"Local PDF extract failed: {exc}") from exc
        return "\n".join(chunks).strip(), page_count

    @staticmethod
    def _needs_tesseract_fallback(text: str, page_count: int) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if len(stripped) < PDF_TEXT_MIN_CHARS:
            return True
        if page_count > 0 and len(stripped) / page_count < 25:
            return True
        alnum = sum(c.isalnum() for c in stripped)
        return alnum / len(stripped) < 0.25

    def extract_text_with_engine(self, file_path: Path) -> PdfExtractionResult:
        """pdfplumber first; Tesseract OCR on scanned/image-only PDFs."""
        plumber_text, page_count = self._extract_pdfplumber_text(file_path)
        if not self._needs_tesseract_fallback(plumber_text, page_count):
            self.last_extraction_engine = "pdfplumber"
            return PdfExtractionResult(text=plumber_text, engine="pdfplumber")

        logger.info(
            "pdfplumber returned %s chars on %s (%s pages) — escalating to Tesseract OCR",
            len(plumber_text.strip()),
            file_path.name,
            page_count,
        )
        try:
            ocr_text = self._ocr.extract_text_from_pdf(file_path)
            self.last_extraction_engine = "tesseract"
            if plumber_text.strip() and len(ocr_text) < len(plumber_text.strip()):
                return PdfExtractionResult(text=plumber_text, engine="pdfplumber")
            return PdfExtractionResult(text=ocr_text, engine="tesseract")
        except ExtractionError:
            if plumber_text.strip():
                self.last_extraction_engine = "pdfplumber"
                return PdfExtractionResult(text=plumber_text, engine="pdfplumber")
            raise ExtractionError(
                f"No text extracted from {file_path.name} (pdfplumber + Tesseract)."
            ) from None

    def extract_text(self, file_path: Path) -> str:
        return self.extract_text_with_engine(file_path).text

    def parse_bank_statement(
        self,
        file_path: Path,
        tenant_id: uuid.UUID,
        bank_name: str,
        bank_account_number: str,
        statement_month: str,
    ) -> list[BankMovement]:
        extracted = self.extract_text_with_engine(file_path)
        movements = self.movements_from_text(
            text=extracted.text,
            tenant_id=tenant_id,
            bank_name=bank_name,
            bank_account_number=bank_account_number,
            statement_month=statement_month,
            source_file_path=str(file_path),
        )
        if not movements and extracted.engine == "pdfplumber":
            logger.info(
                "No movements from pdfplumber text on %s — retrying with Tesseract OCR",
                file_path.name,
            )
            ocr_text = self._ocr.extract_text_from_pdf(file_path)
            self.last_extraction_engine = "tesseract"
            movements = self.movements_from_text(
                text=ocr_text,
                tenant_id=tenant_id,
                bank_name=bank_name,
                bank_account_number=bank_account_number,
                statement_month=statement_month,
                source_file_path=str(file_path),
            )
        if not movements:
            raise ExtractionError(
                f"No movements extracted locally from {file_path.name}. "
                "PDF may be image-only or have an unfamiliar layout."
            )
        return movements

    async def parse_bank_statement_async(
        self,
        file_path: Path,
        tenant_id: uuid.UUID,
        bank_name: str,
        bank_account_number: str,
        statement_month: str,
    ) -> list[BankMovement]:
        import asyncio

        return await asyncio.to_thread(
            self.parse_bank_statement,
            file_path,
            tenant_id,
            bank_name,
            bank_account_number,
            statement_month,
        )

    async def extract_text_async(self, file_path: Path) -> str:
        import asyncio

        return await asyncio.to_thread(self.extract_text, file_path)

    async def extract_text_with_engine_async(self, file_path: Path) -> PdfExtractionResult:
        import asyncio

        return await asyncio.to_thread(self.extract_text_with_engine, file_path)

    def movements_from_text(
        self,
        *,
        text: str,
        tenant_id: uuid.UUID,
        bank_name: str,
        bank_account_number: str,
        statement_month: str,
        source_file_path: str,
    ) -> list[BankMovement]:
        """One movement per dated line with an amount. Identical lines are separate charges
        (two Apple $9.60 on the same day are two movements), so nothing is de-duplicated."""
        movements: list[BankMovement] = []
        pending: tuple[str, str] | None = None  # dated line still waiting for its amount
        pending_age = 0
        side: str | None = None  # current section: "credit" | "debit" | None (unknown)

        def add(date_raw: str, description: str, found: LineAmount) -> None:
            description = description.strip(" -|\t")
            if len(re.findall(r"[A-Za-z]", description)) < 2 or found.amount <= 0:
                return  # e.g. "05/25/23 $8,890.33 $280.00 06/20/23" (payment coupon)
            try:
                movement_date = _normalise_date(date_raw, statement_month)
            except ValueError:
                return
            if found.credit:
                credit = True
            elif side is not None:
                credit = side == "credit"
            else:
                credit = is_payment(description)
            movements.append(
                BankMovement(
                    tenant_id=tenant_id,
                    bank_account_number=bank_account_number,
                    bank_name=bank_name,
                    movement_date=movement_date,
                    description=description[:512],
                    debit_amount=Decimal("0") if credit else found.amount,
                    credit_amount=found.amount if credit else Decimal("0"),
                    source_file_path=source_file_path,
                    statement_month=statement_month,
                )
            )

        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            if len(line) < 4:
                continue
            upper = line.upper()
            if upper.startswith("TOTAL") or any(skip in upper for skip in _SKIP_LINES):
                pending = None
                continue

            if "|" in line:
                cols = [c.strip() for c in line.split("|") if c.strip()]
                if len(cols) >= 3 and re.search(r"\d{1,2}[/-]\d{1,2}", cols[0]):
                    mov = self._row_to_movement(
                        cols,
                        tenant_id,
                        bank_name,
                        bank_account_number,
                        statement_month,
                        source_file_path,
                    )
                    if mov:
                        movements.append(mov)
                    pending = None
                    continue

            m = _DATE_LINE_RE.match(line)
            if m:
                date_raw, rest = m.group(1), m.group(2)
                found = line_amount(rest)
                if found:
                    add(date_raw, rest[: found.start], found)
                    pending = None
                else:
                    pending, pending_age = (date_raw, rest), 0
                continue

            heading = section_side(line)
            if heading:
                side, pending = heading, None
                continue

            if pending:
                pending_age += 1
                found = line_amount(line)
                if found and "$" in line and not _SIDE_NOTE_RE.search(line):
                    add(pending[0], pending[1], found)
                    pending = None
                elif pending_age >= _CONTINUATION_LINES:
                    pending = None

        return movements

    def _row_to_movement(
        self,
        cols: list[str],
        tenant_id: uuid.UUID,
        bank_name: str,
        bank_account_number: str,
        statement_month: str,
        source_file_path: str,
    ) -> BankMovement | None:
        date_raw = cols[0]
        description = cols[1] if len(cols) > 1 else "Unknown"
        debit = Decimal("0")
        credit = Decimal("0")
        if len(cols) >= 4:
            debit = abs(_parse_decimal(cols[2])) if cols[2] else Decimal("0")
            credit = abs(_parse_decimal(cols[3])) if cols[3] else Decimal("0")
        elif len(cols) == 3:
            amt = abs(_parse_decimal(cols[2]))
            debit, credit = amt, Decimal("0")
        if debit == 0 and credit == 0:
            return None
        try:
            movement_date = _normalise_date(date_raw, statement_month)
        except ValueError:
            return None
        return BankMovement(
            tenant_id=tenant_id,
            bank_account_number=bank_account_number,
            bank_name=bank_name,
            movement_date=movement_date,
            description=description[:512],
            debit_amount=debit,
            credit_amount=credit,
            source_file_path=source_file_path,
            statement_month=statement_month,
        )
