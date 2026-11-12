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


# pdfplumber text as Render reads it (words glued together on some banks).
TRUIST_CHECKING_AUG_2025_PDFPLUMBER = """\
Accountsummary
Your previous balance as of07/31/2025 $7,777.03
Checks - 0.00
Otherwithdrawals,debitsandservicecharges -2,838.73
Deposits,creditsandinterest + 1,406.02
Your new balance as of 08/29/2025 = $6,344.32
Otherwithdrawals,debitsandservicecharges
DATE DESCRIPTION AMOUNT($)
08/13 TRUIST ATM CASH WITHDRAWAL 08-12-25 0952 DORAL BRANCH 40.00
08/25 TRUIST ONLINE CREDIT CARD PMT MOBILE TO ****1203 - 875.73
08/25 TRUIST ONLINE CREDIT CARD PMT MOBILE TO ****1203 - 475.00
08/27 DEBIT CARD PURCHASE BNIGLOBALLL 08-26 704-248-6025 NC 0952 1,448.00
Totalotherwithdrawals,debitsandservicecharges = $2,838.73
Deposits,creditsandinterest
DATE DESCRIPTION AMOUNT($)
08/01 DEPOSIT 725.64
08/13 TRUIST ATM CHECK DEPOSIT 08-12-25 21:55 AP78 DORAL BRANCH66784771 680.38
Totaldeposits,creditsandinterest = $1,406.02
"""

TRUIST_CARD_MAY_2023 = """\
Billing Cycle 05/25/2023
Previous Balance $ 9,349.70
Purchases + 687.17 Visit us at Truist.com
Payments - 1,337.16 CR
Finance Charges + 190.62
NEW BALANCE $ 8,890.33
Closing Date New Balance
05/25/23 $8,890.33 $280.00 06/20/23
Trans Date Post Date Plan Name Reference Number Description Amount
04/25 04/26 PPLN01 24492163115000046303007 HIGHLEVEL AGENCY SUB HTTPSGOHIGHLE TX $ 97.00
04/29 04/30 PPLN01 24492163119000016287582 NAME-CHEAP.COM* K90P2Q WWW.NAMECHEAP AZ 14.76
05/10 05/11 00000000000 BUS ONLINE TRANSFER 861.46 CR
05/11 05/12 PPLN01 24492163131000048331907 NAME-CHEAP.COM* FOOIUH WWW.NAMECHEAP AZ 59.04
05/15 05/16 PPLN01 24492153135852791360815 PAYPAL *CALL48 402-935-7733 FL 311.25
05/17 05/17 PPLN01 24692163137109470880042 SPLASHTOP.COM 408-861-1088 CA 99.00
05/19 05/21 PPLN01 24055243139837000309525 WAWA 5357 DORAL FL 43.58
05/19 05/21 00000000000 BUS ONLINE TRANSFER 475.70 CR
05/24 05/25 PPLN01 24765013144010000220628 AKI DORAL FL 62.54
05/25 05/25 CPLN01 74046013145265145664008 FINANCE CHARGE CASH 96.52
05/25 05/25 PPLN01 74046013145266145764004 FINANCE CHARGE 94.10
"""

TRUIST_CARD_AUG_2025 = """\
Billing cycle 07/26/25 - 08/25/25
Accountsummary Paymentinformation
Previousbalance $7,712.92 Newbalance $6,467.74
Payments&othercredits - $1,926.65
Purchases&othercharges - $520.73 Minimumpaymentdue $224.00
Interestcharged + $160.74 Spendingthiscycle
Cardholderactivity
08/01 08/01 00001348828 BRANCH PAYMENT - THANK YOU -$575.92
Cardholderactivity-continued
08/02 08/03 24231685215429677194558 TEXAS ROADHOUSE #2480 MIAMI FL $101.52
08/09 08/10 24226385222012916728009 WAL-MART #4161 MIAMI FL $27.17
08/10 08/11 24943005223263967255344 IHOP 36-158 MIAMI SPRINGSFL $79.72
08/11 08/12 24000775223100024636413 CHAMBER SOUTH CHAMBERSOUTH.FL $25.00
08/14 08/15 24801975226443190762744 CORAL GABLES CHAMBER OF 305-446-9900 FL $50.00
08/16 08/17 24943005229267961848073 COSTCO WHSE #1229 MIAMI FL $237.32
08/23 08/24 0625082301959122 PAYMENTS - THANK YOU -$875.73
08/23 08/24 0625082301959299 PAYMENTS - THANK YOU -$475.00
08/25 08/25 PURCHASE *FINANCE CHARGE* $63.61
08/25 08/25 CASH * FINANCE CHARGE * $97.13
"""

WELLS_FARGO_SEP_2025 = """\
Statement Period 08/23/2025 to 09/21/2025
Previous Balance $3,326.57 Total Credit Limit $3,700
= New Balance $3,151.76
Payments
08/24 08/24 75490967Q0XSLE289 ONLINE PAYMENT THANK YOU 275.57
TOTAL PAYMENTS FOR THIS PERIOD $275.57
Other Credits
8398 09/18 09/18 7443106868EGWLESX UHEALTH DORAL MED CTR-B 305-243-8565 FL 30.00
TOTAL OTHER CREDITS FOR THIS PERIOD $30.00
Purchases, Balance Transfers & Other Charges
8398 08/28 08/28 24034547H05K4B7FR 72424 - DOWNTOWN DADELAND MIAMI FL 5.00
8398 08/28 08/28 24231687GDBHNS0P7 TEXAS ROADHOUSE #2480 MIAMI FL 34.30
8398 08/31 08/31 24760627L00VPRFTA CAFE Y SABOR REST 305-9947754 FL 18.39
8398 09/05 09/05 24801977TDLRLDTE9 LAS TOCAS CORP MIAMI FL 14.11
8398 09/06 09/06 24427337TLYRQDY57 SABOR TROPICAL SUPE MIAMI FL 2.88
TOTAL PURCHASES, BALANCE TRANSFERS & OTHER CHARGES FOR THIS PERIOD $74.68
Interest Charged
09/21 09/21 INTEREST CHARGE ON PURCHASES 56.08
"""

CITI_COSTCO_OCT_2024 = """\
Billing Period: 09/14/24-10/14/24
Previous balance $3,262.95
New balance as of 10/14/24: $3,575.72
Payments, Credits and Adjustments
09/15 ONLINE PAYMENT, THANK YOU -$695.95
as of last statement ......................... +$159.24
Standard Purchases
09/15 09/15 COSTCO WHSE #1229 MIAMI FL $1.61
09/15 09/15 COSTCO WHSE #1229 MIAMI FL $227.24 Total Costco Cash Back Rewards Balance
09/18 DESPEGAR COLOMBIA BOGOTA D.C. CO
Year To Date : $180.59
509,977.00 COLOMBIAN PESO $120.83
09/19 09/19 LA GRANJA LE JEUNE MIAMI FL $18.31
09/20 09/20 COSTCO WHSE #1229 MIAMI FL $25.00
09/20 09/20 COSTCO WHSE #1229 MIAMI FL $144.36
09/21 09/21 DOLPHIN: PBR MIAMI FL $10.00
09/25 09/25 7-ELEVEN 38379 MIAMI FL $27.45
09/25 09/25 COSTCO WHSE #1229 MIAMI FL $3.73
09/25 09/25 COSTCO WHSE #1229 MIAMI FL $46.25
09/26 09/26 LA GRANJA DOWNTOWN MIAMI FL $19.56
09/26 09/26 SQ *INTERCONTINENTAL MIAMMIAMI FL $22.00
09/28 09/28 STARBUCKS 75866 MIAMI FL $5.17 electric vehicle (EV) charging purchases
09/29 09/29 RESTORE.COM 151-25374087 TX $12.00 worldwide, including gas and EV charging at
Costco1................................................. +$2.58
10/01 10/01 SABOR A COLOMBIA MIAMI FL $42.86
10/01 10/01 FIVE BELOW 6000 MIAMI FL $2.60 3% on restaurants .................... +$3.60
10/01 10/01 COSTCO GAS #1229 MIAMI FL $36.96
3% on eligible travel worldwide.............. +$3.62
10/01 10/01 COSTCO WHSE #1229 MIAMI FL $78.00
10/05 10/05 LAZ PARKING M06285-2 PN DORAL FL $4.00
10/06 10/06 SNAP CRACK HIALEAH HIALEAH FL $59.00 Costco.com ................... +$10.52
10/06 10/06 SABOR A COLOMBIA MIAMI FL $23.67
10/13 10/13 SABOR TROPICAL SUPE MIAMI FL $3.15 1% on all other
purchases ............................................. +$1.03
TOTAL FEES FOR THIS PERIOD $0.00
10/14 INTEREST CHARGED TO STANDARD PURCH $57.19
10/14 INTEREST CHARGED TO PUR PR-01/04/24. $17.78
TOTAL INTEREST FOR THIS PERIOD $74.97
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
        ("bank", TRUIST_CHECKING_AUG_2025_PDFPLUMBER, 6),
        ("card", TRUIST_CARD_MAY_2023, 11),
        ("card", TRUIST_CARD_AUG_2025, 11),
        ("card", WELLS_FARGO_SEP_2025, 8),
        ("card", CITI_COSTCO_OCT_2024, 25),
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


def test_closing_date_from_file_name_when_dates_are_unreadable() -> None:
    from datetime import date

    # Elan January 2025 prints its open/closing dates vertically: no date in the text.
    text = (
        "January2025 Statement Page 1 of3\nPrevious Balance + $14,166.72\nNew Balance = $14,071.52"
    )
    summary = parse_statement_summary(text, "2025-01-23 Statement - Card...5607.pdf")
    assert summary.period_end == date(2025, 1, 23) and summary.month == "2025-01"
    assert parse_statement_summary("", "112125 WellsFargo 8398.pdf").period_end == date(
        2025, 11, 21
    )
    assert parse_statement_summary("", "September 12.pdf").period_end is None


def test_next_statement_closing_date_is_ignored() -> None:
    from datetime import date

    text = (
        "Statement Closing D b ate by_24M LTS 1 W 1/03 /2 H 02 o 5 lidaIf yyou\n"
        "Next Statement Closing Date 12/03/2025\n"
        "Statement Closing Date 11/03/2025\n"
    )
    assert parse_statement_summary(text).period_end == date(2025, 11, 3)


TRUIST_CONSOLIDATED_JUL_2025 = """\
Summary of your accounts
BUSINESS VALUE 200 CHECKING 1100009429296 0.00 page 1
TRUIST SIMPLE BUSINESS CHECKING 1100035034461 7,777.03 page 1
¡ BUSINESS VALUE 200 CHECKING1100009429296
Your previous balance as of06/30/2025 $6,292.89
Your new balance as of 07/31/2025 = $0.00
Otherwithdrawals,debitsandservicecharges
07/09 TRUIST ONLINE CREDIT CARD PMT ONLINE TO ****2433 - 6,292.00
07/23 ACCOUNT CLOSE OUT 6,292.89
Deposits,creditsandinterest
07/18 Payment Reversal BCC 1203 000070920257092025 6,292.00
¡ TRUIST SIMPLE BUSINESS CHECKING1100035034461
Your previous balance as of07/08/2025 $0.00
Your new balance as of 07/31/2025 = $7,777.03
Otherwithdrawals,debitsandservicecharges
07/21 TRUIST ATM CASH WITHDRAWAL 07-19-25 0952 INTERNATIONAL MALL BRANCH 40.00
Deposits,creditsandinterest
07/09 DEPOSIT 300.00
07/21 TRUIST ATM CHECK DEPOSIT 07-19-25 21:25 AE79 INTERNATIONAL MALL BRANCH55798671 857.28
07/30 DEPOSIT 6,659.75
"""  # last deposit = printed total 7,817.03 − 300.00 − 857.28


def test_consolidated_statement_keeps_only_this_account() -> None:
    from src.infrastructure.reconciliation.statement_summary import account_section

    text = account_section(TRUIST_CONSOLIDATED_JUL_2025, "4461")
    summary = parse_statement_summary(text)
    movements = read(text)
    assert (summary.opening, summary.closing) == (Decimal("0.00"), Decimal("7777.03"))
    assert [str(m.debit_amount or m.credit_amount) for m in movements] == [
        "40.00", "300.00", "857.28", "6659.75",
    ]
    assert reconcile_statement("bank", summary.opening, summary.closing, movements)["status"] == (
        STATUS_OK
    )
    assert account_section(CITI_BEST_BUY_SEP_2025, "4809") == CITI_BEST_BUY_SEP_2025


@pytest.mark.parametrize(
    ("name", "month"),
    [(" 012325 WellsFargo 6612.pdf", "2025-01"), (" 010826 WellsFargo 6541.pdf", "2026-01")],
)
def test_drive_names_with_leading_space_keep_their_date(name: str, month: str) -> None:
    from src.infrastructure.drive.classify import classify_drive_file

    plan = classify_drive_file(
        name, f"My Xcell Network CORP/Wells Fargo Credit Cards (various)/6612/{name}"
    )
    assert plan.statement_month == month and plan.fiscal_year == month[:4]


def test_drive_walk_does_not_spend_its_cap_on_imported_files() -> None:
    from src.infrastructure.drive.google_drive_client import DriveNode, GoogleDriveClient

    def node(i: int) -> DriveNode:
        return DriveNode(id=f"f{i}", name=f"{i}.pdf", mime_type="application/pdf", path=f"{i}.pdf")

    client = GoogleDriveClient.__new__(GoogleDriveClient)
    client.list_children = lambda _fid: [node(i) for i in range(5)]  # type: ignore[method-assign]
    got = [n.id for n in client.walk_ingestible("root", max_files=2, skip_ids={"f0", "f1", "f2"})]
    assert got == ["f3", "f4"]


WELLS_FARGO_6612_JUL_2025 = """\
Statement Closing Date 07/23/25
Previous Balance $4,300.42
Credits - $85.59
Payments - $2,686.71
Purchases & Other Charges + $2,495.43
Finance Charges + $64.38
New Balance = $4,087.93
Trans Post Reference Number Description Credits Charges
06/17 06/23 55432865E60WKYYSB LPC PASEO DE LA RIV T CORAL GABLES FL 18.00
06/23 06/23 55432865E612X7QQ4 DNH*GODADDY.COM 480-505-8855 AZ 22.17
06/27 06/27 05436845K2X6R3BVG MICRO CENTER# 185 MIAMI FL 256.77
06/30 06/30 82305095MEHN814TN PADDLE.NET* TAKE CTRL ASTORIA NY 29.98
07/01 07/01 15270215N017HY39R GOOGLE GSUITE_MYXCELLC MOUNTAIN VIEW CA 14.40
07/05 07/05 85586685V0XSLXMXF ONLINE ACH PAYMENT THANK YOU 675.75
07/06 07/06 55310205W70J6GBF2 BURLINGTON STORES 348 MIAMI FL 379.72
07/07 07/07 15270215V01EFA0VZ CUBAVERA MIAMI FL 48.14
07/10 07/10 55546505ZBN6GV2JD CORAL GABLES G4 PARKIN CORAL GABLES FL 8.00
07/11 07/11 823050961EHMF2WRA APOLLO.IO COVINA CA 59.00
07/11 07/11 827111660EHMPZD9F OPENAI *CHATGPT SUBSCR SAN FRANCISCO CA 20.00
07/13 07/13 5543286625YQKAPSP DNH*GODADDY.COM 480-505-8855 AZ 57.38
07/15 07/15 5543286655Z5W8GA8 LPC PASEO DE LA RIV T CORAL GABLES FL 15.00
07/15 07/15 55436876486K2ZSVX TELINTA INC SPRINGFIELD NJ 500.00
07/15 07/15 5104323641YS1GMP9 PAYPAL *CALL48 5612825508 FL 238.63
07/15 07/15 8558668640XSM0GFP ONLINE ACH PAYMENT THANK YOU 875.23
07/15 07/15 8558668640XSM0GFP ONLINE PAYMENT THANK YOU 460.00
07/16 07/16 55310206676MZG8B3 BURLINGTON STORES 1220 DORAL FL 47.24
07/16 07/16 55310206676MZG880 BURLINGTON STORES 1220 DORAL FL 85.59
07/16 07/16 12302026501N96RAR TWILIO Q75SGTHKSP8VCT2 SAN FRANCISCO CA 11.45
07/17 07/17 827111666EHMPKAFT WWW.JUSTINWELSH.ME ACCORD NY 9.00
07/20 07/20 0543684698PL8P1QF VIIRTUE ST PETERSBURG FL 760.55
07/20 07/20 8558668690XSL3D9A ONLINE ACH PAYMENT THANK YOU 675.73
PERIODIC*FINANCE CHARGE* PURCHASES $64.38 CASH ADVANCE $0.00 64.38
"""


def test_wells_fargo_unsigned_credits_column_and_undated_interest() -> None:
    from src.infrastructure.reconciliation.statement_summary import flip_printed_credits

    summary = parse_statement_summary(WELLS_FARGO_6612_JUL_2025)
    movements = flip_printed_credits(read(WELLS_FARGO_6612_JUL_2025), summary.credits)
    assert summary.credits == Decimal("85.59")
    refund = [m for m in movements if m.credit_amount == Decimal("85.59")]
    assert len(refund) == 1 and "BURLINGTON" in refund[0].description
    interest = [m for m in movements if m.description == "FINANCE CHARGE"]
    assert [m.debit_amount for m in interest] == [Decimal("64.38")]
    result = reconcile_statement("card", summary.opening, summary.closing, movements)
    assert result["status"] == STATUS_OK, result


WELLS_FARGO_6612_FEB_2025 = """\
Statement Closing Date 02/20/25
Previous Balance $4,164.50
Credits - $5.90
Payments - $475.50
Purchases & Other Charges + $937.51
Finance Charges + $55.66
New Balance = $4,676.27
01/26 01/26 851015911WGNKZ6T2 FOREVER 21 NAIL LOUNGE MIAMI FL 64.00
01/30 01/30 12302020Y019ATA45 TWILIO QR6G4XGDRJRH63B SAN FRANCISCO CA 10.00
01/31 01/31 5526352106NBG8G9A TEXAS ROADHOUSE #2480 MIAMI FL 83.95
01/31 01/31 82117550Z000A1W81 WWW.TAX1099.COM FAYETTEVILLE AR 2.90
02/01 02/01 5543286105WK9W9TQ GOOGLE *GSUITE_MYXCELL 650-253-0000 CA 14.40
02/01 02/01 8558668110XSLD72T ONLINE ACH PAYMENT THANK YOU 475.50
02/08 02/08 1230202170287JDTV LIDS LOCKER ROOM 8045 MIAMI FL 148.13
02/09 02/09 8230509190005VE0M SP MOUS US NEWARK DE 112.28
02/11 02/11 82305091B0004QXPL APOLLO.IO COVINA CA 59.00
02/11 02/11 82711161A000ABLZE OPENAI *CHATGPT SUBSCR SAN FRANCISCO CA 20.00
02/14 02/14 05587451D0000SG1T LUX REWARDS CASHBACK EASYSAVINGS NY 5.90
02/14 02/14 12302021D01V4GTAY TWILIO C57N2LC2Q8STR56 SAN FRANCISCO CA 10.05
02/17 02/17 82711161G000A0ZMR WWW.JUSTINWELSH.ME ACCORD NY 9.00
02/18 02/18 02703401H24S3XJ1F PREPLY INC. BROOKLINE MA 3.00
02/19 02/19 05436841J8PJDSPM0 VIIRTUE ST PETERSBURG FL 300.00
02/19 02/19 02703401J250EHDAF PREPLY INC. BROOKLINE MA 100.80
PERIODIC*FINANCE CHARGE* PURCHASES $55.66 CASH ADVANCE $0.00 55.66
"""


def test_cashback_already_read_is_not_searched_again() -> None:
    from src.infrastructure.reconciliation.statement_summary import flip_printed_credits

    summary = parse_statement_summary(WELLS_FARGO_6612_FEB_2025)
    movements = flip_printed_credits(read(WELLS_FARGO_6612_FEB_2025), summary.credits)
    assert len([m for m in movements if m.credit_amount]) == 2  # payment + cashback only
    result = reconcile_statement("card", summary.opening, summary.closing, movements)
    assert result["status"] == STATUS_OK, result
