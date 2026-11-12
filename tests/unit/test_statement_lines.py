"""Statement line reader — real My Xcell statements must reconcile to the printed balances.

Texts follow pdfplumber's line layout of each bank (one transaction per line).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from src.infrastructure.ocr.local_pdf_client import LocalPdfClient, line_amount
from src.infrastructure.reconciliation.statement_summary import parse_statement_summary
from src.use_cases.reconcile_statements import STATUS_OK, reconcile_statement

CITI_BEST_BUY_SEP_2025 = """\
Summary of Account Activity Previous Balance $6,058.56 Payments -$1,265.20
Purchases/Other Debits +$448.64 Interest Charged +$149.39 New Balance $5,391.39
Statement Closing Date 09/03/2025 Next Statement Closing Date 10/03/2025
TRANSACTIONS
Trans Date Description Reference # Amount
08/06 SABOR TROPICAL SUPE MIAMI FL 24427336SLYRBWHJ6 $ 4.68
08/08 TEXAS ROADHOUSE #2480 MIAMI FL 24231686XQNLZ44KN $ 31.85
08/10 CLAUDE.AI SUBSCRIPTION ANTHROPIC.COM CA 24011346Y2X6LRQL0 $ 20.00
08/16 SABOR TROPICAL SUPE MIAMI FL 244273374LYRQJFJ1 $ 11.68
08/17 EB *HAPPY HOUR HUSTLE 801-413-7200 CA 240362975LTPXL3DN $ 20.00
08/17 LAS TOCAS CORP MIAMI FL 248019776D04EA0YL $ 22.05
08/19 MILAM'S MARKET #1 MIAMI FL 244273377LYRFNT0N $ 18.94
08/21 THE FRESH MARKET 221 DORAL FL 24231687AD4JH5YX8 $ 12.00
08/23 WAWA 5357 DORAL FL 24055247QD6VSGFB8 $ 21.81
08/23 HIGHLEVEL INC. GOHIGHLEVEL.C TX 24492167B2X53Z4W3 $ 10.00
08/24 WHOLEFDS PEM 10193 PEMBROKE PINE FL 24137467D01FKAHX1 $ 52.33
08/25 X CORP. PAID FEATURES ABOUT.X.COM TX 24011347E2X4KH8D1 $ 8.00
08/25 SABOR TROPICAL SUPE MIAMI FL 24427337DLYRAVP58 $ 9.35
08/25 HIGHLEVEL AGENCY SUB GOHIGHLEVEL.C TX 24492167D2X5FPQB6 $ 97.00
08/27 EL CHURRASCASO GRILL MIAMI LAKES FL 24431867G0VZ56VE1 $ 31.99
08/29 TST* GRAZIANOS MARKET COR CORAL GABLES FLD 24137467HEJKHYHQS $ 27.77
08/30 LAS TOCAS CORP MIAMI FL 24801977KDEB2AKLN $ 49.19
TOTAL CARD ENDING 4809 $ 448.64
08/23 ONLINE PAYMENT DEERFIELD IL 74269377QEYB6371A $ 789.76-
09/01 ONLINE PAYMENT DEERFIELD IL 74269377MEYB6VXJL $ 475.44-
TOTAL FEES FOR THIS PERIOD $ 0.00
INTEREST CHARGED
09/03 INTEREST CHARGE ON PURCHASES $ 149.39
TOTAL INTEREST FOR THIS PERIOD $ 149.39
"""

WELLS_FARGO_NOV_2025 = """\
WELLS FARGO CREDIT CARD Account ending in 8398 Statement Period 10/23/2025 to 11/21/2025
Previous Balance $3,033.09
+ Fees Charged $0.00 + Interest Charged $52.31 = New Balance $2,846.31
Trans Date Post Date Reference Number Description Credits Charges
Payments
11/08 11/08 75490969T0XSL72SG ONLINE PAYMENT THANK YOU 125.75
11/18 11/18 7549096A20XSL9S9S ONLINE PAYMENT THANK YOU 135.00
TOTAL PAYMENTS FOR THIS PERIOD $260.75
Purchases, Balance Transfers & Other Charges
8398 11/02 11/02 24801979KFKBPVMP3 LAS TOCAS CORP MIAMI FL 21.66
TOTAL PURCHASES, BALANCE TRANSFERS & OTHER CHARGES FOR THIS PERIOD $21.66
Interest Charged
11/21 11/21 INTEREST CHARGE ON PURCHASES 52.31
"""

ELAN_SEP_2025 = """\
Open Date: 08/26/2025 Closing Date: 09/24/2025 Account: #### #### #### 5607
Previous Balance + $13,808.20 Payments - $429.00 Purchases + $512.85 Interest Charged + $286.14
New Balance = $14,178.19
Payments and Other Credits
Post Trans Date Date Ref # Transaction Description Amount Notation
09/17 09/17 MTC PAYMENT THANK YOU $429.00 CR
TOTAL THIS PERIOD $429.00 CR
Purchases and Other Debits
08/26 08/26 5426 CHAMBER SOUTH CHAMBERSOUTH. FL $50.00
08/27 08/26 5868 CORAL GABLES CHAMBER O 305-446-9900 FL $50.00
09/04 09/03 1670 LINKEDIN SN *534225033 LNKD.IN/BILL CA $79.99
09/11 09/10 2911 TEXAS ROADHOUSE #2659 RICHMOND TX $60.64
09/12 09/11 1361 KATY BNI INC. 205-792-6277 TX $15.00
09/15 09/14 9482 TST* GRAN COLOMBIA - K KATY TX $60.22
09/22 09/22 7624 THE UNCOMMON BUSINESS WWW.THEUNCOMM MN $197.00
TOTAL THIS PERIOD $512.85
Interest Charged
09/24 INTEREST CHARGE ON PURCHASES $286.14
"""

TRUIST_CHECKING_AUG_2025 = """\
Your previous balance as of 07/31/2025 $7,777.03
Your new balance as of 08/29/2025 = $6,344.32
Other withdrawals, debits and service charges
DATE DESCRIPTION AMOUNT($)
08/13 TRUIST ATM CASH WITHDRAWAL 08-12-25 0952 DORAL BRANCH 40.00
08/25 TRUIST ONLINE CREDIT CARD PMT MOBILE TO ****1203 - 875.73
08/25 TRUIST ONLINE CREDIT CARD PMT MOBILE TO ****1203 - 475.00
08/27 DEBIT CARD PURCHASE BNIGLOBALLL 08-26 704-248-6025 NC 0952 1,448.00
Total other withdrawals, debits and service charges = $2,838.73
Deposits, credits and interest
DATE DESCRIPTION AMOUNT($)
08/01 DEPOSIT 725.64
08/13 TRUIST ATM CHECK DEPOSIT 08-12-25 21:55 AP78 DORAL BRANCH 66784771 680.38
Total deposits, credits and interest = $1,406.02
"""


def read(text: str):
    month = parse_statement_summary(text).month
    return LocalPdfClient.__new__(LocalPdfClient).movements_from_text(
        text=text,
        tenant_id=uuid.uuid4(),
        bank_name="Bank",
        bank_account_number="0000",
        statement_month=month,
        source_file_path="/var/data/ledgerai_uploads/doc.pdf",
    )


@pytest.mark.parametrize(
    ("kind", "text", "lines"),
    [
        ("card", CITI_BEST_BUY_SEP_2025, 20),
        ("card", WELLS_FARGO_NOV_2025, 4),
        ("card", ELAN_SEP_2025, 9),
        ("bank", TRUIST_CHECKING_AUG_2025, 6),
    ],
)
def test_real_statements_reconcile(kind: str, text: str, lines: int) -> None:
    movements = read(text)
    summary = parse_statement_summary(text)
    result = reconcile_statement(kind, summary.opening, summary.closing, movements)
    assert len(movements) == lines
    assert result["status"] == STATUS_OK, result


CITI_COSTCO_EXCERPT = """\
Payments, Credits and Adjustments
08/17 ONLINE PAYMENT, THANK YOU -$949.08
09/02 ONLINE PAYMENT, THANK YOU -$975.63 last statement ......... +$250.15
09/07 09/07 FACEBK *K9SXKZQUJ2 650-5434800 CA -$39.91
LUIS GONZALEZ JR Standard Purchases
08/15 08/15 APPLE.COM/BILL 866-712-7753 CA $9.60
08/15 08/15 APPLE.COM/BILL 866-712-7753 CA $9.60
08/19 BB-DGNET LT SOPORTE.COMPUGB
1,395,550.00 COLOMBIAN PESO $347.22
08/19 08/19 TRADE TRAFFIC ORO MEDONTE CA $44.00 3% on restaurants ........ +$6.25
"""


def test_citi_costco_layout() -> None:
    got = [
        (str(m.movement_date)[5:], m.debit_amount, m.credit_amount)
        for m in read("Billing Period: 08/15/25-09/12/25\n" + CITI_COSTCO_EXCERPT)
    ]
    d = Decimal
    assert got == [
        ("08-17", d("0"), d("949.08")),
        ("09-02", d("0"), d("975.63")),  # not the rewards figure printed beside it
        ("09-07", d("0"), d("39.91")),  # refund
        ("08-15", d("9.60"), d("0")),  # two identical charges are two movements
        ("08-15", d("9.60"), d("0")),
        ("08-19", d("347.22"), d("0")),  # amount on the wrapped line
        ("08-19", d("44.00"), d("0")),
    ]


@pytest.mark.parametrize(
    ("line", "amount", "credit"),
    [
        ("APPLE.COM/BILL 866-712-7753 CA $9.60", "9.60", False),
        ("ONLINE PAYMENT DEERFIELD IL 74269377QEYB6371A $ 789.76-", "789.76", True),
        ("MTC PAYMENT THANK YOU $429.00 CR", "429.00", True),
        ("CREDIT CARD PMT MOBILE TO ****1203 - 875.73", "875.73", False),
        ("DEBIT CARD PURCHASE 704-248-6025 NC 0952 1,448.00", "1448.00", False),
    ],
)
def test_line_amount(line: str, amount: str, credit: bool) -> None:
    found = line_amount(line)
    assert found is not None
    assert (found.amount, found.credit) == (Decimal(amount), credit)
