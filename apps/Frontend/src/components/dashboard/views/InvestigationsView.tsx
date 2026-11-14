import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { Network, UserSearch } from 'lucide-react'
import { listBackendCases, updateBackendCase, type BackendCase } from '../../../lib/backendApi'
import { ago } from '../../../lib/format'
import { DecisionBadge, PATTERN_LABEL, decisionColor } from '../../ui/Badges'
import { blurIn } from '../../ui/Reveal'
import { PATTERN_ICON } from '../SignalsList'
import { useConsole } from '../ConsoleContext'
import { Segmented } from '../Panels'
import { Chip, PageHead } from './Common'

export default function InvestigationsView() {
  const { go, focusGraph, inspect } = useConsole()
  const [cases, setCases] = useState<BackendCase[]>([])
  const [filter, setFilter] = useState<BackendCase['status'] | 'ACTIVE' | 'ALL'>('ACTIVE')
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let active = true
    const load = () => listBackendCases('?page=1&pageSize=100').then((response) => active && setCases(response.items)).catch((e) => active && setError(e instanceof Error ? e.message : 'Unable to load cases'))
    void load()
    const timer = window.setInterval(load, 10000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])
  const list = cases.filter((item) => filter === 'ALL' ? true : filter === 'ACTIVE' ? !['CLOSED', 'RESOLVED'].includes(item.status) : item.status === filter)
  const now = Date.now()
  return (
    <>
      <PageHead
        title="Investigations"
        sub="Cases group REVIEW and ESCALATE evidence by shared accounts."
        right={
          <div className="flex gap-1.5">
            {(['ACTIVE', 'OPEN', 'IN_REVIEW', 'ESCALATED', 'RESOLVED', 'CLOSED', 'ALL'] as const).map((f) => (
              <Chip key={f} active={filter === f} onClick={() => setFilter(f)}>
                {f === 'IN_REVIEW' ? 'In review' : f[0] + f.slice(1).toLowerCase()}
              </Chip>
            ))}
          </div>
        }
      />
      {error && <p className="rounded-lg border border-review bg-review-bg px-3 py-2 text-[12px] text-review">{error}</p>}
      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {list.map((i) => (
          <motion.article variants={blurIn} key={i.id} className="rounded-[14px] border border-line bg-surface p-1.5 shadow-card">
            <div className="rounded-[10px] bg-inset p-3.5">
              <div className="flex items-center gap-2.5">
                <span className="grid size-8 place-items-center rounded-[8px]" style={{ background: `color-mix(in srgb, ${decisionColor(i.status === 'ESCALATED' ? 'ESCALATE' : 'REVIEW')} 14%, transparent)`, color: decisionColor(i.status === 'ESCALATED' ? 'ESCALATE' : 'REVIEW') }}>
                  {PATTERN_ICON.MULTI_HOP}
                </span>
                <span className="min-w-0">
                  <span className="block font-mono text-[11.5px] text-muted">{i.id}</span>
                  <span className="block truncate text-[13.5px] font-medium text-ink">{i.title}</span>
                </span>
                <span className="ml-auto text-right">
                    <span className="tabular block text-[20px] font-medium leading-none" style={{ color: decisionColor(i.status === 'ESCALATED' ? 'ESCALATE' : 'REVIEW') }}>
                    {i.priority}
                  </span>
                  <span className="text-[10.5px] text-muted">peak risk</span>
                </span>
              </div>
              <p className="mt-3 truncate font-mono text-[11.5px] text-ink-2">{i.title}</p>
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted">
                <DecisionBadge decision={i.status === 'ESCALATED' ? 'ESCALATE' : 'REVIEW'} />
                <span>
                  <b className="tabular font-medium text-ink-2">{i.accountRefs.length}</b> accounts
                </span>
                <span>
                  <b className="tabular font-medium text-ink-2">{i.transactionRefs.length}</b> transfers
                </span>
                <span>updated {ago(new Date(i.updatedAt).getTime(), now)}</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1">
                {i.accountRefs.slice(0, 8).map((a) => (
                  <button key={a} onClick={() => inspect({ type: 'account', id: a })} className="rounded-[6px] border border-line-strong bg-surface px-1.5 py-0.5 font-mono text-[10.5px] text-ink-2 hover:bg-hover">
                    {a}
                  </button>
                ))}
                {i.accountRefs.length > 8 && <span className="px-1 text-[11px] text-muted">+{i.accountRefs.length - 8}</span>}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 px-1.5 pb-0.5 pt-2">
              <Segmented
                label={`Status ${i.id}`}
                value={i.status}
                onChange={(v) => { void updateBackendCase(i.id, { status: v }).then((updated) => setCases((items) => items.map((item) => item.id === updated.id ? updated : item))).catch((e) => setError(e instanceof Error ? e.message : 'Unable to update case')) }}
                options={[
                  { value: 'OPEN', label: 'Open' },
                  { value: 'IN_REVIEW', label: 'In review' },
                  { value: 'ESCALATED', label: 'Escalated' },
                  { value: 'RESOLVED', label: 'Resolved' },
                  { value: 'CLOSED', label: 'Closed' },
                ]}
              />
              <button onClick={() => i.accountRefs[0] && inspect({ type: 'account', id: i.accountRefs[0] })} className="ml-auto grid size-7 place-items-center rounded-[8px] border border-line-strong text-ink-2 hover:bg-hover" aria-label="Inspect lead account" title="Inspect lead account">
                <UserSearch className="size-3.5" />
              </button>
              <button
                onClick={() => {
                  go('network')
                  focusGraph(i.accountRefs, i.transactionRefs)
                }}
                className="inline-flex h-7 items-center gap-1.5 rounded-[8px] bg-primary px-2.5 text-[12px] font-medium text-primary-fg hover:opacity-90"
              >
                <Network className="size-3.5" /> Trace
              </button>
            </div>
          </motion.article>
        ))}
      </div>
      {!list.length && (
        <div className="flex flex-col items-center gap-2 rounded-[14px] border border-dashed border-line-strong py-16 text-center">
          <span className="size-9 rounded-full border border-dashed border-faint" />
          <p className="text-[13px] text-ink-2">No cases</p>
          <span className="text-[12.5px] text-muted">No cases returned by the backend.</span>
        </div>
      )}
    </>
  )
}
