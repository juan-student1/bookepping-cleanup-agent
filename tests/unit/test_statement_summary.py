"""Billing period + balances from the real My Xcell statement formats (one per bank)."""

from datetime import date
from decimal import Decimal

import pytest

from src.infrastructure.reconciliation.statement_summary import parse_statement_summary

CITI_COSTCO = (
    "LUIS GONZALEZ JR Member Since 2022 Account number ending in: 9597 Billing Period: "
    "12/14/24-01/14/25\nJANUARY STATEMENT Minimum payment due: $117.66 New balance as of "
    "01/14/25: $3,379.26 Payment due date: 02/10/25\nAccount Summary Previous balance $3,770.60 "
    "Payments -$1,166.87 Credits -$0.31 Purchases +$692.18 New balance $3,379.26"
)
ELAN = (
    "Page January 2025 Statement\n1 of 3 Open Date: 12/24/2024 Closing Date: 01/23/2025 "
    "Account: 4798 5100 5852 5607\nNew Balance = $14,071.52 Past Due $0.00\nActivity Summary "
    "New Balance $14,071.52\nPrevious Balance + $14,166.72 Payments - $1,333.72"
)
TRUIST_CARD = (
    "Account number ending in 1203 Statement closing date 08/25/25 New balance $6,467.74\n"
    "Account summary Previous balance $7,712.92 Payments & other credits - $1,926.65 "
    "New balance $6,467.74\nPage 1 of 4 Billing cycle 07/26/25 - 08/25/25"
)
WELLS_FARGO = (
    "Account Number 4465 4203 3160 8398 Payment Due Date 09/16/2025 Minimum Payment $94.00 "
    "New Balance $3,326.57\nWELLS FARGO CREDIT CARD Account ending in 8398 Statement Period "
    "07/23/2025 to 08/22/2025\nAccount Summary\nPrevious Balance $3,369.68 - Payments $145.68"
)
TRUIST_CHECKING = (
    "Your account statement\nFor 08/29/2025\nAccount summary Your previous balance as of "
    "07/31/2025 $7,777.03 Checks - 0.00 Other withdrawals, debits and service charges - 2,838.73 "
    "Deposits, credits and interest + 1,406.02 Your new balance as of 08/29/2025 = $6,344.32"
)
CITI_BEST_BUY = (
    "Summary of Account Activity\nPayment Information Previous Balance Payments Other Credits "
    "Purchases/Other Debits $6,708.70 -$888.74 -$0.46 +$534.60\nNew Balance Minimum Payment Due "
    "Payment Due Date $6,506.52 $218.00 December 28, 2025\n$20,271 Available Cash Limit $200.00 "
    "Amount Statement Next Statement Over Closing Credit Closing Date bby_24M Limit Date LTSW "
    "12/03/2025 01/02/2026 $0.00"
)


@pytest.mark.parametrize(
    ("text", "start", "end", "opening", "closing"),
    [
        (CITI_COSTCO, date(2024, 12, 14), date(2025, 1, 14), "3770.60", "3379.26"),
        (ELAN, date(2024, 12, 24), date(2025, 1, 23), "14166.72", "14071.52"),
        (TRUIST_CARD, date(2025, 7, 26), date(2025, 8, 25), "7712.92", "6467.74"),
        (WELLS_FARGO, date(2025, 7, 23), date(2025, 8, 22), "3369.68", "3326.57"),
        (TRUIST_CHECKING, date(2025, 8, 1), date(2025, 8, 29), "7777.03", "6344.32"),
        (CITI_BEST_BUY, None, date(2025, 12, 3), "6708.70", "6506.52"),
    ],
    ids=["citi-costco", "elan", "truist-card", "wells-fargo", "truist-checking", "citi-best-buy"],
)
def test_reads_period_and_balances(text, start, end, opening, closing) -> None:
    s = parse_statement_summary(text)
    assert (s.period_start, s.period_end) == (start, end)
    assert (s.opening, s.closing) == (Decimal(opening), Decimal(closing))
    assert s.month == end.strftime("%Y-%m")


def test_missing_data_stays_none() -> None:
    s = parse_statement_summary("Random invoice without balances 04/05/2025")
    assert s.period_end is None and not s.has_balances
