import { useState } from 'react'
import { engine } from '../../../engine/SimulationEngine'
import type { Decision, Pattern } from '../../../engine/types'
import { PATTERN_LABEL } from '../../ui/Badges'
import SignalsList, { PATTERN_ICON } from '../SignalsList'
import { useConsole, useEngine } from '../ConsoleContext'
import { Card, Segmented } from '../Panels'
import { PageHead } from './Common'
import { motion } from 'motion/react'
import { blurIn } from '../../ui/Reveal'

const PATTERNS: Pattern[] = ['FAN_OUT', 'FAN_IN', 'RAPID_PASS_THROUGH', 'CYCLE', 'MULTI_HOP']
const WEIGHT_KEY = { FAN_OUT: 'fan_out', FAN_IN: 'fan_in', RAPID_PASS_THROUGH: 'pass_through', CYCLE: 'cycle', MULTI_HOP: 'multi_hop' } as const

export default function SignalsView() {
  useEngine()
  const { inspect, focusGraph, go } = useConsole()
  const [pattern, setPattern] = useState<Pattern | null>(null)
  const [decision, setDecision] = useState<Decision | 'ALL'>('ALL')
  const all = engine.signals
  const list = all.filter((s) => (!pattern || s.patterns.includes(pattern)) && (decision === 'ALL' || s.decision === decision)).slice(0, 80)
  return (
    <>
      <PageHead title="Risk Signals" sub="Detected graph patterns with supporting evidence." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {PATTERNS.map((p) => {
          const n = all.filter((s) => s.patterns.includes(p)).length
          const active = pattern === p
          return (
            <motion.button
              variants={blurIn}
              key={p}
              onClick={() => setPattern(active ? null : p)}
              aria-pressed={active}
              className={`rounded-[14px] border p-1.5 text-left shadow-card transition-colors ${active ? 'border-primary bg-surface' : 'border-line bg-surface hover:border-line-strong'}`}
            >
              <div className="rounded-[10px] bg-inset px-3 py-2.5">
                <span className="flex items-center gap-2 text-[12.5px] text-ink-2">
                  <span className="grid size-6 place-items-center rounded-[6px] border border-line bg-surface text-ink">{PATTERN_ICON[p]}</span>
                  {PATTERN_LABEL[p]}
                </span>
                <span className="tabular mt-1.5 block pl-8 text-[22px] font-medium leading-none text-ink">{n}</span>
              </div>
              <span className="flex items-center justify-between px-1.5 pb-0.5 pt-1.5 font-mono text-[10.5px] text-muted">
                {p}
                <span>w {engine.settings.weights[WEIGHT_KEY[p]].toFixed(2)}</span>
              </span>
            </motion.button>
          )
        })}
      </div>
      <Card>
        <div className="flex flex-wrap items-center gap-2 px-4 pb-2 pt-3.5">
          <h2 className="text-[14.5px] font-medium text-ink">{pattern ? PATTERN_LABEL[pattern] : 'All signals'}</h2>
          <span className="tabular text-[12px] text-muted">{list.length} shown</span>
          <span className="ml-auto">
            <Segmented
              label="Decision filter"
              value={decision}
              onChange={setDecision}
              options={[
                { value: 'ALL', label: 'All' },
                { value: 'MONITOR', label: 'Monitor' },
                { value: 'REVIEW', label: 'Review' },
                { value: 'ESCALATE', label: 'Escalate' },
              ]}
            />
          </span>
        </div>
        <div className="px-1.5 pb-2">
          <SignalsList
            signals={list}
            onOpen={(s) => inspect({ type: 'txn', id: s.transactionId })}
            onTrace={(s) => {
              go('network')
              focusGraph(s.involvedAccounts, s.evidenceTransactionIds)
            }}
          />
        </div>
      </Card>
    </>
  )
}
