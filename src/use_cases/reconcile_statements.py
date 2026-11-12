"""
Bank reconciliation per statement (QuickBooks "Reconcile" for each bank / card statement).

For every statement document of a workspace:

    previous balance (printed)  ± movements extracted from that statement  = computed balance
    computed balance  vs  new balance (printed)                            → difference

    bank account:  previous − debits + credits
    credit card:   previous + charges − payments/credits

Also checks the chain between statements of the same account (this statement's previous
balance = last statement's new balance) and repairs what earlier imports left inconsistent:

  * pairing: every movement points to the transaction that was created from it;
  * year rollover: a December movement on a January statement belongs to the previous year.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path, PurePosixPath

from src.domain.models.bank_movement import BankMovement
from src.domain.models.enums import TransactionStatus
from src.domain.models.transaction import FinancialTransaction
from src.infrastructure.reconciliation.statement_chain import StatementPeriodRepository
from src.infrastructure.reconciliation.statement_summary import (
    StatementSummary,
    parse_statement_summary,
)
from src.infrastructure.reports.funding_accounts import funding_from_document
from src.infrastructure.repositories.bank_movement_repository import BankMovementRepository
from src.infrastructure.repositories.supabase_client import get_supabase_client
from src.infrastructure.repositories.transaction_repository import TransactionRepository

logger = logging.getLogger(__name__)

TOLERANCE = Decimal("0.01")
ROLLOVER_GRACE = timedelta(days=7)  # posting dates can trail the closing date by a few days

STATUS_OK = "reconciled"  # computed = printed new balance
STATUS_DIFF = "difference"  # movements missing or extra on this statement
STATUS_NO_BALANCES = "no_balances"  # statement balances could not be read


def file_stem(path: str | None) -> str:
    return PurePosixPath(path or "").stem


# ── Pure rules (unit-tested) ───────────────────────────────────────────────────────────


def pair_links(
    movements: Iterable[BankMovement], transactions: Iterable[FinancialTransaction]
) -> tuple[list[BankMovement], list[FinancialTransaction]]:
    """Point each movement at the transaction created from it; flag both as reconciled."""
    by_movement = {t.bank_movement_id: t for t in transactions if t.bank_movement_id}
    fixed_movements: list[BankMovement] = []
    fixed_txs: list[FinancialTransaction] = []
    for m in movements:
        tx = by_movement.get(m.id)
        if tx is None:
            continue
        if m.matched_transaction_id != tx.id or m.status != TransactionStatus.VERIFIED:
            fixed_movements.append(m.mark_reconciled(transaction_id=tx.id))
        if not tx.reconciled:
            fixed_txs.append(tx.model_copy(update={"reconciled": True}))
    return fixed_movements, fixed_txs


def _previous_year(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # Feb 29
        return d.replace(year=d.year - 1, day=28)


def fix_rollover(movements: Iterable[BankMovement], period_end: date) -> list[BankMovement]:
    """Movements dated after the statement closed belong to the previous year (Dec on Jan)."""
    limit = period_end + ROLLOVER_GRACE
    out: list[BankMovement] = []
    for m in movements:
        if m.movement_date > limit and _previous_year(m.movement_date) <= limit:
            out.append(m.model_copy(update={"movement_date": _previous_year(m.movement_date)}))
    return out


def reconcile_statement(
    kind: str,
    opening: Decimal | None,
    closing: Decimal | None,
    movements: list[BankMovement],
) -> dict:
    """Previous balance ± movements vs printed new balance."""
    debits = sum((m.debit_amount for m in movements), Decimal("0"))
    credits = sum((m.credit_amount for m in movements), Decimal("0"))
    if opening is None or closing is None:
        return {
            "debits": debits,
            "credits": credits,
            "computed": None,
            "difference": None,
            "status": STATUS_NO_BALANCES,
        }
    computed = opening + debits - credits if kind == "card" else opening - debits + credits
    difference = closing - computed
    status = STATUS_OK if abs(difference) <= TOLERANCE else STATUS_DIFF
    return {
        "debits": debits,
        "credits": credits,
        "computed": computed,
        "difference": difference,
        "status": status,
    }


def chain_checks(rows: list[dict]) -> list[dict]:
    """Per account, ordered by closing date: previous balance must equal last new balance."""
    by_account: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_account[r["bank_account_number"]].append(r)
    for items in by_account.values():
        items.sort(key=lambda r: r["_period_end"] or date.min)
        prev: dict | None = None
        for r in items:
            r["prior_closing"] = prev["closing_balance"] if prev else None
            if prev and r["opening_balance"] is not None and prev["closing_balance"] is not None:
                delta = Decimal(str(r["opening_balance"])) - Decimal(str(prev["closing_balance"]))
                r["chain_delta"] = float(delta)
                r["chain_ok"] = abs(delta) <= TOLERANCE
                if not r["chain_ok"]:
                    r["alert_message"] = (
                        f"Saldo inicial {r['opening_balance']:,.2f} ≠ saldo final del extracto "
                        f"anterior {prev['closing_balance']:,.2f} (Δ {delta:,.2f}): falta un extracto "
                        "o un movimiento entre los dos."
                    )
            prev = r
    return rows


# ── Use case ───────────────────────────────────────────────────────────────────────────


@dataclass
class RebuildReport:
    statements: int = 0
    read: int = 0
    with_balances: int = 0
    links_repaired: int = 0
    transactions_flagged: int = 0
    dates_fixed: int = 0
    months_fixed: int = 0
    reconciled: int = 0
    differences: int = 0
    errors: list[str] = field(default_factory=list)


TextReader = Callable[[dict], Awaitable[str]]


async def read_statement_text(doc: dict) -> str:
    """Statement PDF text (local cache or Supabase Storage → pdfplumber / OCR)."""
    from src.infrastructure.ocr.local_pdf_client import LocalPdfClient
    from src.infrastructure.storage.document_storage import resolve_document_bytes

    data = resolve_document_bytes(
        local_path=doc.get("local_path"), storage_path=doc.get("storage_path")
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "statement.pdf"
        path.write_bytes(data)
        return (await LocalPdfClient().extract_text_with_engine_async(path)).text


class ReconcileStatementsUseCase:
    def __init__(
        self,
        movement_repo: BankMovementRepository | None = None,
        transaction_repo: TransactionRepository | None = None,
        periods: StatementPeriodRepository | None = None,
        read_text: TextReader = read_statement_text,
    ) -> None:
        self._movements = movement_repo or BankMovementRepository()
        self._transactions = transaction_repo or TransactionRepository()
        self._periods = periods or StatementPeriodRepository()
        self._read_text = read_text

    async def rebuild(self, workspace_id: uuid.UUID) -> RebuildReport:
        """Re-read every statement, repair links / dates / months and store its balances."""
        report = RebuildReport()
        docs = self._statement_documents(workspace_id)
        movements = await self._movements.list_by_tenant(workspace_id, limit=200_000)
        transactions = await self._transactions.list_by_tenant(workspace_id, limit=200_000)
        by_doc: dict[str, list[BankMovement]] = defaultdict(list)
        for m in movements:
            by_doc[file_stem(m.source_file_path)].append(m)
        tx_by_movement = {t.bank_movement_id: t for t in transactions if t.bank_movement_id}

        changed_movements: dict[uuid.UUID, BankMovement] = {}
        changed_txs: dict[uuid.UUID, FinancialTransaction] = {}
        rows: list[dict] = []
        for doc in docs:
            doc_movements = by_doc.get(str(doc["id"]), [])
            if not doc_movements:
                continue
            report.statements += 1
            try:
                summary = parse_statement_summary(await self._read_text(doc))
                report.read += 1
            except Exception as exc:  # unreadable PDF: still listed, without balances
                logger.warning("Statement %s unreadable: %s", doc["id"], exc)
                report.errors.append(f"{doc.get('file_name')}: {exc}")
                summary = StatementSummary()

            if summary.period_end:
                for fixed in fix_rollover(doc_movements, summary.period_end):
                    changed_movements[fixed.id] = fixed
                    report.dates_fixed += 1
                    tx = tx_by_movement.get(fixed.id)
                    if tx is not None:
                        changed_txs[tx.id] = tx.model_copy(
                            update={"transaction_date": fixed.movement_date}
                        )
            month = summary.month or max(m.movement_date for m in doc_movements).strftime("%Y-%m")
            for m in doc_movements:
                current = changed_movements.get(m.id, m)
                if current.statement_month != month:
                    changed_movements[m.id] = current.model_copy(update={"statement_month": month})
                    report.months_fixed += 1
            if summary.has_balances:
                report.with_balances += 1
            fa = funding_from_document(doc)
            first = doc_movements[0]
            rows.append(
                {
                    "tenant_id": str(workspace_id),
                    "bank_name": first.bank_name,
                    "bank_account_number": first.bank_account_number,
                    "statement_month": month,
                    "opening_balance": float(summary.opening)
                    if summary.opening is not None
                    else None,
                    "closing_balance": float(summary.closing)
                    if summary.closing is not None
                    else None,
                    "movement_count": len(doc_movements),
                    "source_document_id": str(doc["id"]),
                    "chain_ok": None,
                    "chain_delta": None,
                    "paused": False,
                    "alert_message": None,
                    "_period_end": summary.period_end,
                    "_kind": fa.kind if fa else "bank",
                }
            )

        # Pairing repair runs on the date-fixed movements so nothing is saved twice.
        current = [changed_movements.get(m.id, m) for m in movements]
        current_txs = [changed_txs.get(t.id, t) for t in transactions]
        fixed_movements, fixed_txs = pair_links(current, current_txs)
        for m in fixed_movements:
            changed_movements[m.id] = m
        for t in fixed_txs:
            changed_txs[t.id] = t
        report.links_repaired = len(fixed_movements)
        report.transactions_flagged = len(fixed_txs)

        await self._movements.save_many(list(changed_movements.values()))
        await self._transactions.save_many(list(changed_txs.values()))

        final_by_doc: dict[str, list[BankMovement]] = defaultdict(list)
        for m in movements:
            final_by_doc[file_stem(m.source_file_path)].append(changed_movements.get(m.id, m))
        for r in chain_checks(rows):
            result = reconcile_statement(
                r["_kind"],
                None if r["opening_balance"] is None else Decimal(str(r["opening_balance"])),
                None if r["closing_balance"] is None else Decimal(str(r["closing_balance"])),
                final_by_doc[r["source_document_id"]],
            )
            report.reconciled += result["status"] == STATUS_OK
            report.differences += result["status"] == STATUS_DIFF
        self._periods.replace_for_tenant(
            workspace_id, [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
        )
        return report

    async def statements(self, workspace_id: uuid.UUID) -> list[dict]:
        """Reconciliation table: one row per statement with its difference."""
        docs = {str(d["id"]): d for d in self._statement_documents(workspace_id)}
        movements = await self._movements.list_by_tenant(workspace_id, limit=200_000)
        by_doc: dict[str, list[BankMovement]] = defaultdict(list)
        for m in movements:
            by_doc[file_stem(m.source_file_path)].append(m)
        out: list[dict] = []
        for p in self._periods.list_by_tenant(workspace_id, limit=5000):
            doc_id = str(p.get("source_document_id") or "")
            doc = docs.get(doc_id, {})
            fa = funding_from_document(doc) if doc else None
            doc_movements = by_doc.get(doc_id, [])
            opening = p.get("opening_balance")
            closing = p.get("closing_balance")
            result = reconcile_statement(
                fa.kind if fa else "bank",
                None if opening is None else Decimal(str(opening)),
                None if closing is None else Decimal(str(closing)),
                doc_movements,
            )
            dates = [m.movement_date for m in doc_movements]
            out.append(
                {
                    "document_id": doc_id or None,
                    "file_name": doc.get("file_name"),
                    "account": fa.name
                    if fa
                    else f"{p.get('bank_name')} {p.get('bank_account_number')}",
                    "account_kind": fa.kind if fa else "bank",
                    "bank_account_number": p.get("bank_account_number"),
                    "statement_month": p.get("statement_month"),
                    "first_date": str(min(dates)) if dates else None,
                    "last_date": str(max(dates)) if dates else None,
                    "movement_count": len(doc_movements),
                    "opening_balance": opening,
                    "closing_balance": closing,
                    "debits": float(result["debits"]),
                    "credits": float(result["credits"]),
                    "computed_closing": None
                    if result["computed"] is None
                    else float(result["computed"]),
                    "difference": None
                    if result["difference"] is None
                    else float(result["difference"]),
                    "status": result["status"],
                    "chain_ok": p.get("chain_ok"),
                    "chain_delta": p.get("chain_delta"),
                    "alert_message": p.get("alert_message"),
                }
            )
        out.sort(key=lambda r: (r["account"], r["statement_month"] or ""))
        return out

    @staticmethod
    def _statement_documents(workspace_id: uuid.UUID) -> list[dict]:
        client = get_supabase_client()
        rows: list[dict] = []
        page = 1000
        while True:
            data = (
                client.table("documents")
                .select("id,file_name,drive_path,vendor,queue_payload,local_path,storage_path")
                .eq("workspace_id", str(workspace_id))
                .range(len(rows), len(rows) + page - 1)
                .execute()
                .data
                or []
            )
            rows.extend(data)
            if len(data) < page:
                return rows
