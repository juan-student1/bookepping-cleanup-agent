"""
Statement summary — billing period and balances printed on a bank / card statement.

Every statement prints the same three facts, each bank in its own words:

    Citi Costco    Billing Period: 12/14/24-01/14/25 · Previous balance $3,770.60
                   · New balance $3,379.26
    Elan           Open Date: 12/24/2024 Closing Date: 01/23/2025
                   · Previous Balance + $14,166.72 · New Balance = $14,071.52
    Truist card    Billing cycle 07/26/25 - 08/25/25 · Previousbalance $7,712.92
                   · Newbalance $6,467.74 (words glued together)
    Wells Fargo    Statement Period 07/23/2025 to 08/22/2025 · Previous Balance $3,369.68
    Truist bank    Your previous balance as of07/31/2025 $7,777.03
                   · Your new balance as of 08/29/2025 = $6,344.32
    Citi Best Buy  Previous Balance … $6,708.70 · Statement Closing Date … 12/03/2025
                   (not "Next Statement Closing Date")

Bank reconciliation = previous balance ± movements of the statement = new balance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

_DATE = r"(\d{1,2})/(\d{1,2})/(\d{2,4})"
_MONEY = r"(-?\s*\$\s*-?\s*[\d,]+\.\d{2}|-?[\d,]+\.\d{2})"
_GAP = r"[^$\d]{0,90}?"  # label words between a caption and its amount (no digits)

_RANGE_RES = [
    re.compile(
        rf"(?:billing\s+period|billing\s+cycle|statement\s+period)\s*:?\s*{_DATE}\s*(?:-|–|—|to|through)\s*{_DATE}",
        re.I,
    ),
    re.compile(rf"open\s+date\s*:?\s*{_DATE}.{{0,40}}?closing\s+date\s*:?\s*{_DATE}", re.I | re.S),
]
_AS_OF_RANGE_RE = re.compile(
    rf"previous\s+balance\s+as\s+of\s+{_DATE}.{{0,400}}?new\s+balance\s+as\s+of\s+{_DATE}",
    re.I | re.S,
)
_END_RES = [
    re.compile(rf"(?:statement\s*)?closing\s*date\s*:?\s*{_DATE}", re.I),
    re.compile(rf"new\s*balance\s*as\s*of\s*{_DATE}", re.I),
    re.compile(rf"(?:statement\s*)?closing\s*date.{{0,70}}?{_DATE}", re.I | re.S),
]
_OPENING_RE = re.compile(
    rf"(?:previous|beginning|opening)\s*balance(?:\s*as\s*of\s*{_DATE})?{_GAP}{_MONEY}", re.I | re.S
)
_CLOSING_RE = re.compile(
    rf"(?:new|ending|closing)\s*balance(?:\s*as\s*of\s*{_DATE})?\s*[:=]?{_GAP}{_MONEY}", re.I | re.S
)


@dataclass(frozen=True)
class StatementSummary:
    period_start: date | None = None
    period_end: date | None = None
    opening: Decimal | None = None
    closing: Decimal | None = None

    @property
    def month(self) -> str | None:
        """Statement month = month of the closing date (YYYY-MM)."""
        return self.period_end.strftime("%Y-%m") if self.period_end else None

    @property
    def has_balances(self) -> bool:
        return self.opening is not None and self.closing is not None


def _to_date(month: str, day: str, year: str) -> date | None:
    y = int(year)
    if y < 100:
        y += 2000
    try:
        return date(y, int(month), int(day))
    except ValueError:
        return None


def _to_money(raw: str) -> Decimal | None:
    negative = "-" in raw
    cleaned = re.sub(r"[^\d.]", "", raw)
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -value if negative else value


def _period(text: str) -> tuple[date | None, date | None]:
    for rx in _RANGE_RES:
        m = rx.search(text)
        if m:
            start, end = _to_date(*m.group(1, 2, 3)), _to_date(*m.group(4, 5, 6))
            if start and end and start <= end:
                return start, end
    m = _AS_OF_RANGE_RE.search(text)
    if m:
        prev_close, end = _to_date(*m.group(1, 2, 3)), _to_date(*m.group(4, 5, 6))
        if prev_close and end and prev_close < end:
            return prev_close + timedelta(days=1), end
    for rx in _END_RES:
        for m in rx.finditer(text):
            # "Next Statement Closing Date" is next month's, not this statement's.
            if "next" in (text[max(0, m.start() - 16) : m.start()] + m.group(0)).lower():
                continue
            end = _to_date(*m.group(1, 2, 3))
            if end:
                return None, end
    return None, None


_NAME_ISO_RE = re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)")
_NAME_MMDDYY_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})(?!\d)")


def closing_date_from_name(file_name: str | None) -> date | None:
    """Closing date written in the file name: "2025-01-23 Statement…", "112125 WellsFargo…"."""
    name = (file_name or "").strip()
    m = _NAME_ISO_RE.search(name)
    if m:
        return _to_date(m.group(2), m.group(3), m.group(1))
    m = _NAME_MMDDYY_RE.match(name)
    if m:
        return _to_date(m.group(1), m.group(2), m.group(3))
    return None


def parse_statement_summary(text: str, file_name: str | None = None) -> StatementSummary:
    """Billing period and previous / new balance from a statement's text (None when absent).
    When the dates cannot be read (e.g. printed vertically), the file name's date is used."""
    text = text or ""
    start, end = _period(text)
    if end is None:
        end = closing_date_from_name(file_name)
    opening = _OPENING_RE.search(text)
    closing = _CLOSING_RE.search(text)
    return StatementSummary(
        period_start=start,
        period_end=end,
        opening=_to_money(opening.group(4)) if opening else None,
        closing=_to_money(closing.group(4)) if closing else None,
    )
