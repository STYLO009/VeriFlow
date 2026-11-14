import { useState } from 'react'
import { motion } from 'motion/react'
import { Network, UserSearch } from 'lucide-react'
import { engine } from '../../../engine/SimulationEngine'
import type { InvestigationStatus } from '../../../engine/types'
import { ago } from '../../../lib/format'
import { DecisionBadge, PATTERN_LABEL, decisionColor } from '../../ui/Badges'
import { blurIn } from '../../ui/Reveal'
import { PATTERN_ICON } from '../SignalsList'
import { useConsole, useEngine } from '../ConsoleContext'
import { Segmented } from '../Panels'
import { Chip, PageHead } from './Common'

export default function InvestigationsView() {
  useEngine()
  const { go, focusGraph, inspect } = useConsole()
  const [filter, setFilter] = useState<InvestigationStatus | 'ACTIVE' | 'ALL'>('ACTIVE')
  const list = engine.investigations.filter((i) => (filter === 'ALL' ? true : filter === 'ACTIVE' ? i.status !== 'CLOSED' : i.status === filter))
  const now = engine.now()
  return (
    <>
      <PageHead
        title="Investigations"
        sub="Cases group REVIEW and ESCALATE evidence by shared accounts."
        right={
          <div className="flex gap-1.5">
            {(['ACTIVE', 'OPEN', 'IN_REVIEW', 'CLOSED', 'ALL'] as const).map((f) => (
              <Chip key={f} active={filter === f} onClick={() => setFilter(f)}>
                {f === 'IN_REVIEW' ? 'In review' : f[0] + f.slice(1).toLowerCase()}
              </Chip>
            ))}
          </div>
        }
      />
      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {list.map((i) => (
          <motion.article variants={blurIn} key={i.id} className="rounded-[14px] border border-line bg-surface p-1.5 shadow-card">
            <div className="rounded-[10px] bg-inset p-3.5">
              <div className="flex items-center gap-2.5">
                <span className="grid size-8 place-items-center rounded-[8px]" style={{ background: `color-mix(in srgb, ${decisionColor(i.decision)} 14%, transparent)`, color: decisionColor(i.decision) }}>
                  {PATTERN_ICON[i.pattern]}
                </span>
                <span className="min-w-0">
                  <span className="block font-mono text-[11.5px] text-muted">{i.id}</span>
                  <span className="block truncate text-[13.5px] font-medium text-ink">{PATTERN_LABEL[i.pattern]} network</span>
                </span>
                <span className="ml-auto text-right">
                  <span className="tabular block text-[20px] font-medium leading-none" style={{ color: decisionColor(i.decision) }}>
                    {i.maxScore.toFixed(1)}
                  </span>
                  <span className="text-[10.5px] text-muted">peak risk</span>
                </span>
              </div>
              <p className="mt-3 truncate font-mono text-[11.5px] text-ink-2">{i.title}</p>
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted">
                <DecisionBadge decision={i.decision} />
                <span>
                  <b className="tabular font-medium text-ink-2">{i.accounts.length}</b> accounts
                </span>
                <span>
                  <b className="tabular font-medium text-ink-2">{i.transactionIds.length}</b> transfers
                </span>
                <span>opened {ago(i.openedAt, now)}</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1">
                {i.accounts.slice(0, 8).map((a) => (
                  <button key={a} onClick={() => inspect({ type: 'account', id: a })} className="rounded-[6px] border border-line-strong bg-surface px-1.5 py-0.5 font-mono text-[10.5px] text-ink-2 hover:bg-hover">
                    {a}
                  </button>
                ))}
                {i.accounts.length > 8 && <span className="px-1 text-[11px] text-muted">+{i.accounts.length - 8}</span>}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 px-1.5 pb-0.5 pt-2">
              <Segmented
                label={`Status ${i.id}`}
                value={i.status}
                onChange={(v) => engine.setInvestigationStatus(i.id, v)}
                options={[
                  { value: 'OPEN', label: 'Open' },
                  { value: 'IN_REVIEW', label: 'In review' },
                  { value: 'CLOSED', label: 'Closed' },
                ]}
              />
              <button onClick={() => inspect({ type: 'account', id: i.accounts[0] })} className="ml-auto grid size-7 place-items-center rounded-[8px] border border-line-strong text-ink-2 hover:bg-hover" aria-label="Inspect lead account" title="Inspect lead account">
                <UserSearch className="size-3.5" />
              </button>
              <button
                onClick={() => {
                  go('network')
                  focusGraph(i.accounts, i.transactionIds)
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
          <button onClick={() => engine.triggerScenario('MULE_NETWORK')} className="text-[12.5px] text-muted underline underline-offset-4 hover:text-ink">
            Trigger a mule network
          </button>
        </div>
      )}
    </>
  )
}
