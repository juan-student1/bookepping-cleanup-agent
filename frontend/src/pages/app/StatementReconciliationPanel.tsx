import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import {
  api,
  type ReconciliationRebuild,
  type StatementReconciliation,
  type StatementReconciliationSummary,
} from '../../lib/api'
import { useLocale } from '../../i18n'
import { cn } from '../../lib/utils'

const POLL_MS = 5000

function amount(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function StatusBadge({ row }: { row: StatementReconciliation }) {
  const { t } = useLocale()
  const tone =
    row.status === 'reconciled'
      ? 'bg-success text-success-foreground'
      : row.status === 'difference'
        ? 'bg-destructive/15 text-destructive'
        : 'bg-secondary text-secondary-foreground'
  return (
    <span className={cn('whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium', tone)}>
      {t(`reconciliation.status.${row.status}`)}
    </span>
  )
}

/**
 * Bank reconciliation per statement: previous balance ± the statement's movements must equal
 * the printed new balance, and each statement must open with the previous one's new balance.
 */
export default function StatementReconciliationPanel({
  workspaceId,
  onRebuilt,
}: {
  workspaceId: string
  onRebuilt?: () => void
}) {
  const { t } = useLocale()
  const [rows, setRows] = useState<StatementReconciliation[]>([])
  const [summary, setSummary] = useState<StatementReconciliationSummary | null>(null)
  const [rebuild, setRebuild] = useState<ReconciliationRebuild>({ status: 'idle' })
  const [account, setAccount] = useState('')
  const [onlyIssues, setOnlyIssues] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await api.reconciliationStatements(workspaceId)
      setRows(data.statements)
      setSummary(data.summary)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('common.error'))
    }
  }, [workspaceId, t])

  const poll = useCallback(async () => {
    try {
      const state = await api.reconciliationRebuildStatus(workspaceId)
      setRebuild(state)
      if (state.status === 'running') {
        timer.current = window.setTimeout(() => void poll(), POLL_MS)
      } else if (state.status === 'done') {
        await load()
        onRebuilt?.()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t('common.error'))
    }
  }, [workspaceId, load, onRebuilt, t])

  useEffect(() => {
    void load()
    void poll()
    return () => {
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [load, poll])

  async function startRebuild() {
    setError(null)
    try {
      setRebuild(await api.rebuildReconciliation(workspaceId))
      timer.current = window.setTimeout(() => void poll(), POLL_MS)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('common.error'))
    }
  }

  const accounts = useMemo(() => Array.from(new Set(rows.map((r) => r.account))).sort(), [rows])
  const visible = useMemo(
    () =>
      rows.filter(
        (r) =>
          (!account || r.account === account) &&
          (!onlyIssues || r.status !== 'reconciled' || r.chain_ok === false),
      ),
    [rows, account, onlyIssues],
  )
  const running = rebuild.status === 'running'

  return (
    <section className="mb-8 animate-fade-up rounded-xl border border-border bg-card p-4 soft-shadow">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <h2 className="text-lg font-semibold tracking-tight">{t('reconciliation.byStatement')}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t('reconciliation.byStatementHint')}</p>
        </div>
        <button
          type="button"
          onClick={() => void startRebuild()}
          disabled={running}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-60"
        >
          <RefreshCw className={cn('h-4 w-4', running && 'animate-spin')} />
          {running ? t('reconciliation.rebuilding') : t('reconciliation.rebuild')}
        </button>
      </div>

      {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      {rebuild.status === 'error' && (
        <p className="mt-3 text-sm text-destructive">{rebuild.error}</p>
      )}
      {rebuild.status === 'done' && rebuild.report && (
        <p className="mt-3 text-sm text-muted-foreground">
          {t('reconciliation.rebuildDone')
            .replace('{read}', String(rebuild.report.read))
            .replace('{links}', String(rebuild.report.links_repaired))
            .replace('{dates}', String(rebuild.report.dates_fixed))}
        </p>
      )}

      {summary && summary.statements > 0 && (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: t('reconciliation.statements'), value: summary.statements },
            { label: t('reconciliation.status.reconciled'), value: summary.reconciled },
            { label: t('reconciliation.status.difference'), value: summary.differences },
            { label: t('reconciliation.chainBreaks'), value: summary.chain_breaks },
          ].map((kpi) => (
            <div key={kpi.label} className="rounded-lg border border-border bg-background p-3">
              <p className="text-xs text-muted-foreground">{kpi.label}</p>
              <p className="mt-0.5 text-xl font-semibold tabular-nums">{kpi.value}</p>
            </div>
          ))}
        </div>
      )}

      {rows.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">{t('reconciliation.byStatementEmpty')}</p>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <select
              className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
              value={account}
              onChange={(e) => setAccount(e.target.value)}
            >
              <option value="">{t('reconciliation.allAccounts')}</option>
              {accounts.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={onlyIssues}
                onChange={(e) => setOnlyIssues(e.target.checked)}
              />
              {t('reconciliation.onlyIssues')}
            </label>
          </div>
          <div className="table-scroll mt-3">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="px-2 py-2 font-medium">{t('reconciliation.account')}</th>
                  <th className="px-2 py-2 font-medium">{t('reconciliation.month')}</th>
                  <th className="px-2 py-2 text-right font-medium">{t('reconciliation.lines')}</th>
                  <th className="px-2 py-2 text-right font-medium">{t('reconciliation.opening')}</th>
                  <th className="px-2 py-2 text-right font-medium">{t('reconciliation.charges')}</th>
                  <th className="px-2 py-2 text-right font-medium">{t('reconciliation.credits')}</th>
                  <th className="px-2 py-2 text-right font-medium">{t('reconciliation.computed')}</th>
                  <th className="px-2 py-2 text-right font-medium">{t('reconciliation.closing')}</th>
                  <th className="px-2 py-2 text-right font-medium">{t('reconciliation.difference')}</th>
                  <th className="px-2 py-2 font-medium">{t('reconciliation.statusLabel')}</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr
                    key={`${r.document_id}-${r.statement_month}`}
                    className="border-b border-border/60 align-top"
                    title={r.alert_message || r.file_name || undefined}
                  >
                    <td className="px-2 py-2">
                      <span className="font-medium">{r.account}</span>
                      <span className="block text-xs text-muted-foreground">
                        {r.account_kind === 'card'
                          ? t('reconciliation.kindCard')
                          : t('reconciliation.kindBank')}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-2 py-2">
                      {r.statement_month}
                      {r.chain_ok === false && (
                        <span className="block text-xs text-destructive">
                          {t('reconciliation.chainBreak')}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums">{r.movement_count}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{amount(r.opening_balance)}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{amount(r.debits)}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{amount(r.credits)}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{amount(r.computed_closing)}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{amount(r.closing_balance)}</td>
                    <td
                      className={cn(
                        'px-2 py-2 text-right font-medium tabular-nums',
                        r.status === 'difference' && 'text-destructive',
                      )}
                    >
                      {amount(r.difference)}
                    </td>
                    <td className="px-2 py-2">
                      <StatusBadge row={r} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
