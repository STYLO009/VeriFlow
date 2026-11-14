import { useState } from 'react'
import { engine } from '../../../engine/SimulationEngine'
import { ago, formatINRCompact } from '../../../lib/format'
import { PatternBadge, ScoreText, decisionColor, scoreDecision } from '../../ui/Badges'
import { useConsole, useEngine } from '../ConsoleContext'
import { Card } from '../Panels'
import { Chip, PageHead, Pager, SearchInput } from './Common'

const PAGE = 20

export default function AccountsView() {
  useEngine()
  const { inspect } = useConsole()
  const [q, setQ] = useState('')
  const [flaggedOnly, setFlagged] = useState(false)
  const [page, setPage] = useState(0)
  const now = engine.now()
  const s = q.trim().toUpperCase()
  const rows = [...engine.risk.values()]
    .map((r) => ({ ...r, live: engine.accountScore(r.accountId), meta: engine.accounts.get(r.accountId) }))
    .filter((r) => (!s || r.accountId.includes(s)) && (!flaggedOnly || r.live >= 30))
    .sort((a, b) => b.live - a.live || b.inCount + b.outCount - (a.inCount + a.outCount))
  const pages = Math.ceil(rows.length / PAGE)
  const p = Math.min(page, Math.max(0, pages - 1))
  return (
    <>
      <PageHead title="Accounts" sub="Account-level risk, kept separate from transaction risk." />
      <Card>
        <div className="flex flex-wrap items-center gap-2 px-4 pb-3 pt-3.5">
          <SearchInput value={q} onChange={(v) => (setQ(v), setPage(0))} placeholder="Search account…" />
          <Chip active={flaggedOnly} onClick={() => (setFlagged(!flaggedOnly), setPage(0))}>
            Risk ≥ 30 only
          </Chip>
        </div>
        <div className="overflow-x-auto px-1.5 scrollbar-thin">
          <table className="w-full min-w-[820px] border-separate border-spacing-0 text-[12.5px]">
            <thead>
              <tr className="bg-inset text-left text-[11.5px] text-muted">
                {['Account', 'Type', 'Age', 'Risk', 'Incoming', 'Outgoing', 'Patterns', 'Last seen'].map((h) => (
                  <th key={h} scope="col" className="px-3 py-2 font-normal first:rounded-l-[8px] first:pl-3.5 last:rounded-r-[8px]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(p * PAGE, p * PAGE + PAGE).map((r) => (
                <tr key={r.accountId} onClick={() => inspect({ type: 'account', id: r.accountId })} className="cursor-pointer transition-colors hover:bg-hover">
                  <td className="border-b border-line py-2.5 pl-3.5 pr-3 font-mono text-[12px] text-ink">{r.accountId}</td>
                  <td className="border-b border-line px-3 text-[11.5px] text-ink-2">{r.meta?.kind === 'MERCHANT' ? 'Merchant' : 'Personal'}</td>
                  <td className="tabular border-b border-line px-3 text-muted">{r.meta?.accountAgeDays ?? '—'}d</td>
                  <td className="border-b border-line px-3">
                    <span className="flex items-center gap-2">
                      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-inset">
                        <span className="block h-full rounded-full" style={{ width: `${r.live}%`, background: decisionColor(scoreDecision(r.live)) }} />
                      </span>
                      <ScoreText score={r.live} />
                    </span>
                  </td>
                  <td className="tabular border-b border-line px-3 text-ink-2">
                    {r.inCount} · {formatINRCompact(r.inAmount)}
                  </td>
                  <td className="tabular border-b border-line px-3 text-ink-2">
                    {r.outCount} · {formatINRCompact(r.outAmount)}
                  </td>
                  <td className="border-b border-line px-3">
                    <span className="flex flex-wrap gap-1">{r.patterns.length ? r.patterns.slice(0, 3).map((pt) => <PatternBadge key={pt} pattern={pt} />) : <span className="text-faint">—</span>}</span>
                  </td>
                  <td className="tabular border-b border-line px-3 text-muted">{r.lastSeen ? ago(r.lastSeen, now) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pager page={p} pages={pages} total={rows.length} onPage={setPage} />
      </Card>
    </>
  )
}
