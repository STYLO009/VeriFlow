import { useEffect, useState } from 'react'
import { listBackendAlerts, type BackendAlert } from '../../../lib/backendApi'
import type { Decision, Pattern } from '../../../engine/types'
import { PATTERN_LABEL } from '../../ui/Badges'
import SignalsList, { PATTERN_ICON } from '../SignalsList'
import { useConsole } from '../ConsoleContext'
import { Card, Segmented } from '../Panels'
import { PageHead } from './Common'
import { motion } from 'motion/react'
import { blurIn } from '../../ui/Reveal'

const PATTERNS: Pattern[] = ['FAN_OUT', 'FAN_IN', 'RAPID_PASS_THROUGH', 'CYCLE', 'MULTI_HOP']
const patternFor = (value: string): Pattern => {
  const normalized = value.toUpperCase().replace(/-/g, '_')
  return normalized === 'PASS_THROUGH' || normalized === 'RAPID_PASS_THROUGH' ? 'RAPID_PASS_THROUGH' : PATTERNS.includes(normalized as Pattern) ? normalized as Pattern : 'MULTI_HOP'
}

export default function SignalsView() {
  const { inspect, focusGraph, go } = useConsole()
  const [alerts, setAlerts] = useState<BackendAlert[]>([])
  const [error, setError] = useState<string | null>(null)
  const [pattern, setPattern] = useState<Pattern | null>(null)
  const [decision, setDecision] = useState<Decision | 'ALL'>('ALL')
  useEffect(() => {
    let active = true
    const load = () => listBackendAlerts('?page=1&pageSize=100').then((response) => active && setAlerts(response.items)).catch((e) => active && setError(e instanceof Error ? e.message : 'Unable to load risk signals'))
    void load()
    const timer = window.setInterval(load, 10000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])
  const all = alerts.flatMap((alert) => {
    const backendSignals = alert.signals?.length ? alert.signals : [{ patternType: 'MULTI_HOP', severity: 'HIGH', involvedAccountIds: [], evidenceTransactionIds: [] }]
    return backendSignals.map((signal, index) => {
      const p = patternFor(signal.patternType)
      const accounts = Array.isArray(signal.involvedAccountIds) ? signal.involvedAccountIds.filter((v): v is string => typeof v === 'string') : []
      const txns = Array.isArray(signal.evidenceTransactionIds) ? signal.evidenceTransactionIds.filter((v): v is string => typeof v === 'string') : []
      return { id: `${alert.id}-${index}`, pattern: p, patterns: [p], severity: signal.severity as 'LOW' | 'MEDIUM' | 'HIGH', riskScore: alert.riskScore, decision: alert.decision, transactionId: alert.transactionRef ?? alert.id, involvedAccounts: accounts, evidenceTransactionIds: txns, detectedAt: new Date(alert.createdAt).getTime(), summary: `${p} detected by ${alert.modelVersion}`, scenario: 'EXTERNAL' as const }
    })
  })
  const list = all.filter((s) => (!pattern || s.patterns.includes(pattern)) && (decision === 'ALL' || s.decision === decision)).slice(0, 80)
  return (
    <>
      <PageHead title="Risk Signals" sub="Detected graph patterns with supporting evidence." />
      {error && <p className="rounded-lg border border-review bg-review-bg px-3 py-2 text-[12px] text-review">{error}</p>}
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
                <span>backend</span>
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
