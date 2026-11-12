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
from typing import Protocol

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
from src.infrastructure.repositories.document_repository import list_statement_sources
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


def _line_key(m: BankMovement) -> tuple:
    return (m.movement_date, m.debit_amount, m.credit_amount)


def diff_lines(
    stored: list[BankMovement], printed: list[BankMovement]
) -> tuple[list[BankMovement], list[BankMovement]]:
    """Statement lines missing from what is stored (to add) and stored lines the statement does
    not print (to remove). Same date and amount on the same side = same line; repeats count."""
    pool: dict[tuple, list[BankMovement]] = defaultdict(list)
    for m in stored:
        pool[_line_key(m)].append(m)
    add: list[BankMovement] = []
    for m in printed:
        bucket = pool.get(_line_key(m))
        if bucket:
            bucket.pop()
        else:
            add.append(m)
    remove = [m for bucket in pool.values() for m in bucket]
    return add, remove


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
        items.sort(key=lambda r: (r.get("statement_month") or "", r.get("_period_end") or date.min))
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
                        f"anterior {prev['closing_balance']:,.2f} (Δ {delta:,.2f}): "
                        "falta un extracto "
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
    lines_added: int = 0
    lines_removed: int = 0
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


class LineReader(Protocol):
    def __call__(
        self,
        *,
        text: str,
        tenant_id: uuid.UUID,
        bank_name: str,
        bank_account_number: str,
        statement_month: str,
        source_file_path: str,
    ) -> list[BankMovement]: ...


class MovementRecorder(Protocol):
    async def record(
        self, movements: list[BankMovement], *, file_path: str, engine: str
    ) -> list[BankMovement]: ...


def read_statement_lines(**kwargs) -> list[BankMovement]:
    from src.infrastructure.ocr.local_pdf_client import LocalPdfClient

    return LocalPdfClient().movements_from_text(**kwargs)


def default_recorder() -> MovementRecorder:
    from src.use_cases.process_statement import ProcessStatementUseCase

    return ProcessStatementUseCase()


Progress = Callable[[int, int], None]


@dataclass
class _Statement:
    """One statement during a rebuild: its movements after repair and its row."""

    doc: dict
    movements: list[BankMovement]
    added: list[BankMovement] = field(default_factory=list)
    removed: list[BankMovement] = field(default_factory=list)
    row: dict = field(default_factory=dict)


class ReconcileStatementsUseCase:
    def __init__(
        self,
        movement_repo: BankMovementRepository | None = None,
        transaction_repo: TransactionRepository | None = None,
        periods: StatementPeriodRepository | None = None,
        read_text: TextReader = read_statement_text,
        read_lines: LineReader = read_statement_lines,
        recorder: MovementRecorder | None = None,
    ) -> None:
        self._movements = movement_repo or BankMovementRepository()
        self._transactions = transaction_repo or TransactionRepository()
        self._periods = periods or StatementPeriodRepository()
        self._read_text = read_text
        self._read_lines = read_lines
        self._recorder = recorder

    async def rebuild(
        self, workspace_id: uuid.UUID, on_progress: Progress | None = None
    ) -> RebuildReport:
        """Re-read every statement: repair dates, months and pairing; when the stored lines do not
        add up to the printed balance and a fresh read of the statement does, replace the lines
        that differ (lines that match keep their category). Then store and reconcile."""
        report = RebuildReport()
        movements = await self._movements.list_by_tenant(workspace_id, limit=200_000)
        transactions = await self._transactions.list_by_tenant(workspace_id, limit=200_000)
        by_doc: dict[str, list[BankMovement]] = defaultdict(list)
        for m in movements:
            by_doc[file_stem(m.source_file_path)].append(m)
        tx_by_movement = {t.bank_movement_id: t for t in transactions if t.bank_movement_id}
        docs = [d for d in self._statement_documents(workspace_id) if by_doc.get(str(d["id"]))]

        changed_movements: dict[uuid.UUID, BankMovement] = {}
        changed_txs: dict[uuid.UUID, FinancialTransaction] = {}
        statements: list[_Statement] = []
        for done, doc in enumerate(docs):
            if on_progress:
                on_progress(done, len(docs))
            st = await self._repair_statement(
                workspace_id, doc, by_doc[str(doc["id"])], tx_by_movement, report
            )
            stored = {m.id: m for m in by_doc[str(doc["id"])]}
            for m in st.movements:
                if m != stored[m.id]:
                    changed_movements[m.id] = m
                    tx = tx_by_movement.get(m.id)
                    if tx is not None and tx.transaction_date != m.movement_date:
                        changed_txs[tx.id] = tx.model_copy(
                            update={"transaction_date": m.movement_date}
                        )
            statements.append(st)
        report.statements = len(statements)

        # Lines that are not on the statement go, with their transaction. Movements point at
        # transactions (FK), so links are dropped first, then movements, then transactions.
        removed_ids = {m.id for st in statements for m in st.removed}
        removed_tx_ids = [tx_by_movement[mid].id for mid in removed_ids if mid in tx_by_movement]
        if removed_ids:
            await self._movements.unlink_transactions(removed_tx_ids)
            await self._movements.delete_many(list(removed_ids))
            await self._transactions.delete_many(removed_tx_ids)
            gone_txs = set(removed_tx_ids)
            for tid in gone_txs:
                changed_txs.pop(tid, None)
            for mid in removed_ids:
                changed_movements.pop(mid, None)
            for m in movements:  # kept movements that pointed at a deleted transaction
                current = changed_movements.get(m.id, m)
                if m.id not in removed_ids and current.matched_transaction_id in gone_txs:
                    changed_movements[m.id] = current.model_copy(
                        update={"matched_transaction_id": None}
                    )
        report.lines_removed = len(removed_ids)
        kept = [changed_movements.get(m.id, m) for m in movements if m.id not in removed_ids]
        kept_txs = [
            changed_txs.get(t.id, t) for t in transactions if t.bank_movement_id not in removed_ids
        ]

        # Pairing repair runs on the repaired movements so nothing is saved twice.
        fixed_movements, fixed_txs = pair_links(kept, kept_txs)
        for m in fixed_movements:
            changed_movements[m.id] = m
        for t in fixed_txs:
            changed_txs[t.id] = t
        report.links_repaired = len(fixed_movements)
        report.transactions_flagged = len(fixed_txs)
        await self._movements.save_many(list(changed_movements.values()))
        await self._transactions.save_many(list(changed_txs.values()))

        # Lines the statement prints that were missing: categorised, mirrored and paired.
        for st in statements:
            if st.added:
                recorder = self._recorder or default_recorder()
                st.added = await recorder.record(
                    st.added, file_path=st.added[0].source_file_path or "", engine="pdfplumber"
                )
                report.lines_added += len(st.added)

        rows: list[dict] = []
        for st in statements:
            final = [changed_movements.get(m.id, m) for m in st.movements] + st.added
            st.row["movement_count"] = len(final)
            st.row["_final"] = final
            rows.append(st.row)
        for r in chain_checks(rows):
            result = reconcile_statement(
                r["_kind"],
                None if r["opening_balance"] is None else Decimal(str(r["opening_balance"])),
                None if r["closing_balance"] is None else Decimal(str(r["closing_balance"])),
                r["_final"],
            )
            report.reconciled += result["status"] == STATUS_OK
            report.differences += result["status"] == STATUS_DIFF
        self._periods.replace_for_tenant(
            workspace_id, [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
        )
        if on_progress:
            on_progress(len(docs), len(docs))
        return report

    async def _repair_statement(
        self,
        workspace_id: uuid.UUID,
        doc: dict,
        stored: list[BankMovement],
        tx_by_movement: dict,
        report: RebuildReport,
    ) -> _Statement:
        text = ""
        try:
            text = await self._read_text(doc)
            summary = parse_statement_summary(text, doc.get("file_name"))
            report.read += 1
        except Exception as exc:  # unreadable PDF: still listed, without balances
            logger.warning("Statement %s unreadable: %s", doc["id"], exc)
            report.errors.append(f"{doc.get('file_name')}: {exc}")
            summary = StatementSummary()

        current = list(stored)
        if summary.period_end:
            fixed = {m.id: m for m in fix_rollover(current, summary.period_end)}
            report.dates_fixed += len(fixed)
            current = [fixed.get(m.id, m) for m in current]
        month = summary.month or max(m.movement_date for m in current).strftime("%Y-%m")
        report.months_fixed += sum(1 for m in current if m.statement_month != month)
        current = [
            m if m.statement_month == month else m.model_copy(update={"statement_month": month})
            for m in current
        ]
        if summary.has_balances:
            report.with_balances += 1

        fa = funding_from_document(doc)
        kind = fa.kind if fa else "bank"
        st = _Statement(doc=doc, movements=current)
        if summary.has_balances and text:
            first = current[0]
            parsed = self._read_lines(
                text=text,
                tenant_id=workspace_id,
                bank_name=first.bank_name,
                bank_account_number=first.bank_account_number,
                statement_month=month,
                source_file_path=first.source_file_path or "",
            )
            add, remove = diff_lines(current, parsed)
            if add or remove:
                gone = {m.id for m in remove}
                candidate = [m for m in current if m.id not in gone] + add
                before = reconcile_statement(kind, summary.opening, summary.closing, current)
                after = reconcile_statement(kind, summary.opening, summary.closing, candidate)
                # Only a re-read that ties out to the printed balance replaces stored lines.
                if after["status"] == STATUS_OK and before["status"] != STATUS_OK:
                    st.movements = [m for m in current if m.id not in gone]
                    st.added, st.removed = add, remove

        first = current[0]
        st.row = {
            "tenant_id": str(workspace_id),
            "bank_name": first.bank_name,
            "bank_account_number": first.bank_account_number,
            "statement_month": month,
            "opening_balance": float(summary.opening) if summary.opening is not None else None,
            "closing_balance": float(summary.closing) if summary.closing is not None else None,
            "source_document_id": str(doc["id"]),
            "chain_ok": None,
            "chain_delta": None,
            "paused": False,
            "alert_message": None,
            "_period_end": summary.period_end,
            "_kind": kind,
        }
        return st

    async def statement_detail(self, workspace_id: uuid.UUID, document_id: str) -> dict:
        """Why one statement does not reconcile: lines the statement prints that are not stored
        (missing) and stored lines it does not print (extra), plus what a re-read would give."""
        doc = next(
            (d for d in self._statement_documents(workspace_id) if str(d["id"]) == document_id),
            None,
        )
        if doc is None:
            raise LookupError(document_id)
        stored = [
            m
            for m in await self._movements.list_by_tenant(workspace_id, limit=200_000)
            if file_stem(m.source_file_path) == document_id
        ]
        text = await self._read_text(doc)
        summary = parse_statement_summary(text, doc.get("file_name"))
        fa = funding_from_document(doc)
        kind = fa.kind if fa else "bank"
        first = stored[0] if stored else None
        printed = (
            self._read_lines(
                text=text,
                tenant_id=workspace_id,
                bank_name=first.bank_name,
                bank_account_number=first.bank_account_number,
                statement_month=summary.month or first.statement_month or "",
                source_file_path=first.source_file_path or "",
            )
            if first
            else []
        )
        missing, extra = diff_lines(stored, printed)
        reread = reconcile_statement(kind, summary.opening, summary.closing, printed)

        def line(m: BankMovement) -> dict:
            return {
                "date": str(m.movement_date),
                "description": m.description,
                "debit": float(m.debit_amount),
                "credit": float(m.credit_amount),
            }

        return {
            "document_id": document_id,
            "file_name": doc.get("file_name"),
            "account": fa.name if fa else None,
            "period_start": str(summary.period_start) if summary.period_start else None,
            "period_end": str(summary.period_end) if summary.period_end else None,
            "opening_balance": None if summary.opening is None else float(summary.opening),
            "closing_balance": None if summary.closing is None else float(summary.closing),
            "missing": [line(m) for m in sorted(missing, key=_line_key)],
            "extra": [line(m) for m in sorted(extra, key=_line_key)],
            "reread_status": reread["status"],
            "reread_difference": None
            if reread["difference"] is None
            else float(reread["difference"]),
            "text": text[:30_000],
        }

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
        return list_statement_sources(workspace_id)
