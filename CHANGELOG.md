# Unreleased — Sprint 20 (2026-11-12)

- Every bank movement is paired with its own transaction in both directions when the statement is processed; the fuzzy re-matcher that gave up on identical charges is gone.
- Statement month comes from the statement's closing date; December lines on January statements get the previous year.
- Bank reconciliation per statement: previous balance ± movements = printed new balance, plus the chain between consecutive statements of each account.
- `POST /api/reconciliation/rebuild` re-reads all statements in the background and repairs links, dates and months already stored; `GET /api/reconciliation/statements` lists the result.
- Reconciliation page: "Bank reconciliation by statement" panel.

# Unreleased — Sprint 19 (2026-10-30)

- Profit and Loss and Balance Sheet follow the TPC QuickBooks templates on the web (company, title, period, Total column, "Total for X" groups, Cash Basis footer).
- Balance Sheet is cumulative "as of" the period end: prior years → Retained Earnings, current year → Net Income.
- Balance Sheet lists each bank (Bank Accounts) and credit card (Credit Cards) from the statement's Drive folder; double entry, so Assets = Liabilities + Equity always holds.
- Download each report as Excel with live subtotal formulas; CPA package uses the same sheets.
- Removed unused endpoints (`/reports/pnl`, `/reports/sql`), v1 statement models and dead UI/i18n.

# LedgerAI v1.0.0

First reviewable release of the bookkeeping cleanup agent.

## What it does
- Ingest PDFs/Excel from Google Drive (nested folders: bank → account → year)
- Classify: bank statement vs invoice vs spreadsheet
- Extract with LlamaParse + structure with OpenAI; categorize via embeddings vs chart of accounts
- Review/approve transactions, reconcile bank movements, close periods
- Profit & loss (P&L): revenue − expenses for a date range

## Stack
FastAPI · React (Vite) · Supabase · Google Drive · LlamaParse · OpenAI · Groq (voice)

## Notes
- Workspaces are deletable (cascades docs / txs / movements / CoA)
- Documents show Drive folder provenance and APIs used
- Sidebar collapsible; dashboard explains the live agent pipeline
