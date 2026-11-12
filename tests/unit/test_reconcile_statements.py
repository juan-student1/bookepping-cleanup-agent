"""Bank reconciliation per statement — cases taken from My Xcell's real statements."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from src.domain.models.bank_movement import BankMovement
from src.domain.models.enums import DocumentSource, TransactionStatus, TransactionType
from src.domain.models.transaction import ExtractionMetadata, FinancialTransaction
from src.use_cases.reconcile_statements import (
    STATUS_DIFF,
    STATUS_NO_BALANCES,
    STATUS_OK,
    ReconcileStatementsUseCase,
    chain_checks,
    fix_rollover,
    pair_links,
    reconcile_statement,
)

TENANT = uuid.uuid4()


def mov(day: date, *, debit: str = "0", credit: str = "0", doc: str = "citi-jan", desc: str = "x"):
    return BankMovement(
        tenant_id=TENANT,
        bank_account_number="1802",
        bank_name="Citi",
        movement_date=day,
        description=desc,
        debit_amount=Decimal(debit),
        credit_amount=Decimal(credit),
        source_file_path=f"/var/data/ledgerai_uploads/{doc}.pdf",
        statement_month="2025-01",
    )


def tx_for(m: BankMovement, *, reconciled: bool = False) -> FinancialTransaction:
    return FinancialTransaction(
        tenant_id=TENANT,
        transaction_date=m.movement_date,
        description=m.description,
        amount=m.debit_amount or m.credit_amount,
        transaction_type=TransactionType.EXPENSE if m.debit_amount else TransactionType.INCOME,
        bank_movement_id=m.id,
        reconciled=reconciled,
        status=TransactionStatus.VERIFIED,
        metadata=ExtractionMetadata(
            source=DocumentSource.BANK_STATEMENT,
            raw_file_path=m.source_file_path,
            extraction_model="test",
            confidence_score=1.0,
        ),
    )


def test_identical_charges_are_paired_with_their_own_transaction() -> None:
    # Two Apple $9.60 charges on 11/21: the old fuzzy match found 2 candidates and gave up.
    a = mov(date(2025, 11, 21), debit="9.60", desc="APPLE.COM/BILL 866-712-7753 CA")
    b = mov(date(2025, 11, 21), debit="9.60", desc="APPLE.COM/BILL CUPERTINO CA")
    ta, tb = tx_for(a), tx_for(b)
    fixed_movements, fixed_txs = pair_links([a, b], [ta, tb])
    linked = {m.id: m.matched_transaction_id for m in fixed_movements}
    assert linked == {a.id: ta.id, b.id: tb.id}
    assert all(m.status == TransactionStatus.VERIFIED for m in fixed_movements)
    assert all(t.reconciled for t in fixed_txs)


def test_pairing_is_idempotent() -> None:
    a = mov(date(2025, 3, 1), debit="10")
    ta = tx_for(a, reconciled=True)
    linked = a.mark_reconciled(transaction_id=ta.id)
    assert pair_links([linked], [ta]) == ([], [])


def test_december_on_a_january_statement_is_last_year() -> None:
    dec = mov(date(2025, 12, 28), debit="245.49", desc="COSTCO WHSE #1229")
    jan = mov(date(2025, 1, 11), debit="40.00")
    fixed = fix_rollover([dec, jan], period_end=date(2025, 1, 14))
    assert [m.movement_date for m in fixed] == [date(2024, 12, 28)]


@pytest.mark.parametrize(
    ("kind", "opening", "closing", "status"),
    [
        ("card", "3770.60", "3379.26", STATUS_OK),  # Citi Costco Jan 2025, all lines present
        ("card", "3770.60", "3500.00", STATUS_DIFF),
        ("card", None, "3379.26", STATUS_NO_BALANCES),
    ],
)
def test_card_statement_math(kind, opening, closing, status) -> None:
    movements = [
        mov(date(2024, 12, 13), credit="375.04"),
        mov(date(2024, 12, 28), credit="395.38"),
        mov(date(2025, 1, 10), credit="396.45"),
        mov(date(2024, 12, 13), credit="0.31"),
        mov(date(2025, 1, 5), debit="692.18"),
        mov(date(2025, 1, 14), debit="83.66"),
    ]
    result = reconcile_statement(
        kind,
        None if opening is None else Decimal(opening),
        Decimal(closing),
        movements,
    )
    assert result["status"] == status
    if status == STATUS_OK:
        assert result["difference"] == Decimal("0.00")


def test_bank_statement_math_truist_checking_august() -> None:
    movements = [
        mov(date(2025, 8, 13), debit="40.00"),
        mov(date(2025, 8, 25), debit="875.73"),
        mov(date(2025, 8, 25), debit="475.00"),
        mov(date(2025, 8, 27), debit="1448.00"),
        mov(date(2025, 8, 1), credit="725.64"),
        mov(date(2025, 8, 13), credit="680.38"),
    ]
    result = reconcile_statement("bank", Decimal("7777.03"), Decimal("6344.32"), movements)
    assert result["status"] == STATUS_OK


def test_missing_payments_show_as_difference() -> None:
    # Elan Jan 2025: purchases + interest were read, the two "CR" payments were not.
    movements = [mov(date(2025, 1, 6), debit="913.11"), mov(date(2025, 1, 23), debit="325.41")]
    result = reconcile_statement("card", Decimal("14166.72"), Decimal("14071.52"), movements)
    assert result["status"] == STATUS_DIFF
    assert result["difference"] == Decimal("-1333.72")  # exactly the two missing payments


def test_chain_between_statements() -> None:
    rows = [
        {
            "bank_account_number": "1802",
            "opening_balance": 3770.60,
            "closing_balance": 3379.26,
            "_period_end": date(2025, 1, 14),
            "alert_message": None,
        },
        {
            "bank_account_number": "1802",
            "opening_balance": 3379.26,
            "closing_balance": 3000.00,
            "_period_end": date(2025, 2, 14),
            "alert_message": None,
        },
        {
            "bank_account_number": "1802",
            "opening_balance": 2500.00,
            "closing_balance": 2400.00,
            "_period_end": date(2025, 4, 14),
            "alert_message": None,
        },
    ]
    out = chain_checks(rows)
    assert out[1]["chain_ok"] is True
    assert out[2]["chain_ok"] is False and "falta un extracto" in out[2]["alert_message"]


class _Repo:
    def __init__(self, items):
        self.items = list(items)
        self.saved = []

    async def list_by_tenant(self, _tid, **_):
        return self.items

    async def save_many(self, entities, **_):
        self.saved.extend(entities)
        return len(entities)


class _Periods:
    def __init__(self):
        self.rows = []

    def replace_for_tenant(self, _tid, rows):
        self.rows = rows
        return len(rows)

    def list_by_tenant(self, _tid, **_):
        return self.rows


CITI_TEXT = "Billing Period: 12/14/24-01/14/25 Previous balance $100.00 New balance $345.49"


@pytest.mark.asyncio
async def test_rebuild_repairs_and_reconciles(monkeypatch: pytest.MonkeyPatch) -> None:
    dec = mov(date(2025, 12, 28), debit="245.49", doc="citi-jan")  # wrong year
    jan = mov(date(2025, 1, 11), debit="40.00", doc="citi-jan")
    pay = mov(date(2025, 1, 10), credit="40.00", doc="citi-jan", desc="ONLINE PAYMENT, THANK YOU")
    movements = [dec, jan, pay]
    txs = [tx_for(m) for m in movements]
    docs = [
        {
            "id": "citi-jan",
            "file_name": "January 14.pdf",
            "drive_path": "Citi Costco 1802/2025/January 14.pdf",
            "queue_payload": {"bank_name": "Citi", "bank_account_number": "1802"},
        }
    ]
    mrepo, trepo, periods = _Repo(movements), _Repo(txs), _Periods()

    async def read(_doc):
        return CITI_TEXT

    uc = ReconcileStatementsUseCase(mrepo, trepo, periods, read_text=read)
    monkeypatch.setattr(uc, "_statement_documents", lambda _w: docs)
    report = await uc.rebuild(TENANT)

    assert report.dates_fixed == 1 and report.links_repaired == 3
    assert report.reconciled == 1 and report.differences == 0
    saved = {m.id: m for m in mrepo.saved}
    assert saved[dec.id].movement_date == date(2024, 12, 28)
    assert {m.statement_month for m in mrepo.saved} == {"2025-01"}
    moved_tx = next(t for t in trepo.saved if t.bank_movement_id == dec.id)
    assert moved_tx.transaction_date == date(2024, 12, 28) and moved_tx.reconciled
    assert periods.rows[0]["opening_balance"] == 100.0

    mrepo.items = [saved[m.id] for m in movements]
    table = await uc.statements(TENANT)
    assert table[0]["account"] == "Citi Costco 1802"
    assert table[0]["status"] == STATUS_OK and table[0]["difference"] == 0.0


class _Recorder:
    def __init__(self):
        self.recorded = []

    async def record(self, movements, *, file_path, engine):
        self.recorded.extend(movements)
        return movements


class _DeletingRepo(_Repo):
    def __init__(self, items, log=None):
        super().__init__(items)
        self.deleted = []
        self.log = log if log is not None else []

    async def delete_many(self, ids):
        self.deleted.extend(ids)
        self.log.append(("delete", type(self).__name__, len(ids)))

    async def unlink_transactions(self, tx_ids):
        self.log.append(("unlink", len(tx_ids)))


BEST_BUY_TEXT = """\
Previous Balance $100.00 New Balance $65.00
Statement Closing Date 09/03/2025
08/06 SABOR TROPICAL SUPE MIAMI FL $ 4.68
08/08 SABOR TROPICAL SUPE MIAMI FL $ 4.68
08/23 ONLINE PAYMENT DEERFIELD IL 74269377QEYB6371A $ 50.00-
09/03 INTEREST CHARGE ON PURCHASES $ 5.64
"""


@pytest.mark.asyncio
async def test_rebuild_adds_missing_lines_only_when_statement_ties_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.ocr.local_pdf_client import LocalPdfClient

    stored = [
        mov(date(2025, 8, 6), debit="4.68", doc="bby-sep"),
        mov(date(2025, 9, 3), debit="5.64", doc="bby-sep"),
        mov(date(2025, 8, 23), debit="50.00", doc="bby-sep"),  # payment read as a charge
    ]
    docs = [
        {
            "id": "bby-sep",
            "file_name": "September 2025 - 4809.pdf",
            "drive_path": "Citi Best Buy/September 2025 - 4809.pdf",
            "queue_payload": {"bank_name": "Citi"},
        }
    ]
    log: list = []
    mrepo = _DeletingRepo(stored, log)
    trepo = _DeletingRepo([tx_for(m) for m in stored], log)
    recorder = _Recorder()

    async def read(_doc):
        return BEST_BUY_TEXT

    uc = ReconcileStatementsUseCase(
        mrepo,
        trepo,
        _Periods(),
        read_text=read,
        read_lines=LocalPdfClient.__new__(LocalPdfClient).movements_from_text,
        recorder=recorder,
    )
    monkeypatch.setattr(uc, "_statement_documents", lambda _w: docs)
    report = await uc.rebuild(TENANT)

    assert report.lines_added == 2 and report.lines_removed == 1
    assert sorted((m.debit_amount, m.credit_amount) for m in recorder.recorded) == [
        (Decimal("0"), Decimal("50.00")),
        (Decimal("4.68"), Decimal("0")),
    ]
    assert mrepo.deleted == [stored[2].id]  # kept lines (and their categories) are untouched
    assert trepo.deleted == [trepo.items[2].id]
    # links dropped before movements, movements before their transactions (FK order)
    assert [entry[0] for entry in log] == ["unlink", "delete", "delete"]
    assert log[1][2] == 1 and log[2][2] == 1
    assert report.reconciled == 1


@pytest.mark.asyncio
async def test_rebuild_keeps_lines_when_reread_does_not_tie_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = [mov(date(2025, 8, 6), debit="4.68", doc="bby-sep")]
    docs = [
        {
            "id": "bby-sep",
            "file_name": "x.pdf",
            "drive_path": "Citi Best Buy/x.pdf",
            "queue_payload": {},
        }
    ]
    mrepo = _DeletingRepo(stored)

    async def read(_doc):
        return BEST_BUY_TEXT

    uc = ReconcileStatementsUseCase(
        mrepo,
        _DeletingRepo([]),
        _Periods(),
        read_text=read,
        read_lines=lambda **_: [],
        recorder=_Recorder(),
    )
    monkeypatch.setattr(uc, "_statement_documents", lambda _w: docs)
    report = await uc.rebuild(TENANT)
    assert report.lines_removed == 0 and mrepo.deleted == []


@pytest.mark.asyncio
async def test_statement_detail_lists_missing_and_extra_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.ocr.local_pdf_client import LocalPdfClient

    stored = [
        mov(date(2025, 8, 6), debit="4.68", doc="bby-sep"),
        mov(date(2025, 9, 3), debit="5.64", doc="bby-sep"),
        mov(date(2025, 8, 23), debit="50.00", doc="bby-sep"),
    ]
    docs = [
        {
            "id": "bby-sep",
            "file_name": "September 2025 - 4809.pdf",
            "drive_path": "Citi Best Buy/September 2025 - 4809.pdf",
            "queue_payload": {},
        }
    ]

    async def read(_doc):
        return BEST_BUY_TEXT

    uc = ReconcileStatementsUseCase(
        _Repo(stored),
        _Repo([]),
        _Periods(),
        read_text=read,
        read_lines=LocalPdfClient.__new__(LocalPdfClient).movements_from_text,
    )
    monkeypatch.setattr(uc, "_statement_documents", lambda _w: docs)
    detail = await uc.statement_detail(TENANT, "bby-sep")

    assert [(m["date"], m["debit"], m["credit"]) for m in detail["missing"]] == [
        ("2025-08-08", 4.68, 0.0),
        ("2025-08-23", 0.0, 50.0),
    ]
    assert [(m["date"], m["debit"]) for m in detail["extra"]] == [("2025-08-23", 50.0)]
    assert detail["reread_status"] == STATUS_OK
    assert (detail["opening_balance"], detail["closing_balance"]) == (100.0, 65.0)
