import { ArrowDownLeft, ArrowRight, ArrowUpRight, FolderSearch, Network } from 'lucide-react'
import { motion } from 'motion/react'
import { engine } from '../../engine/SimulationEngine'
import type { SignalKey, TxnRecord } from '../../engine/types'
import { ago, clock, formatINR, formatINRCompact, formatMs } from '../../lib/format'
import { DecisionBadge, PATTERN_LABEL, PatternBadge, ScoreText, StatusText, decisionColor, scoreDecision } from '../ui/Badges'
import { blurIn, stagger } from '../ui/Reveal'
import { useConsole, useEngine, type InspectTarget } from './ConsoleContext'
import { Sparkline } from './Panels'

const SIGNALS: { key: SignalKey; label: string }[] = [
  { key: 'fan_out', label: 'fan_out' },
  { key: 'fan_in', label: 'fan_in' },
  { key: 'pass_through', label: 'pass_through' },
  { key: 'cycle', label: 'cycle' },
  { key: 'multi_hop', label: 'multi_hop' },
]

export default function RiskInspector({ target, inline }: { target: InspectTarget; inline?: boolean }) {
  useEngine()
  return (
    <motion.div key={target.type + target.id} initial="hidden" animate="show" variants={stagger(0.05)} className="space-y-4 p-4">
      {target.type === 'txn' ? <TxnView id={target.id} inline={inline} /> : <AccountView id={target.id} inline={inline} />}
    </motion.div>
  )
}

function Block({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <motion.section variants={blurIn}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[12px] font-medium text-ink-2">{title}</h3>
        {right}
      </div>
      {children}
    </motion.section>
  )
}

function Gauge({ score }: { score: number }) {
  const bands: [number, number, string][] = [
    [0, 30, 'var(--allow)'],
    [30, 60, 'var(--monitor)'],
    [60, 80, 'var(--review)'],
    [80, 100, 'var(--escalate)'],
  ]
  return (
    <div className="relative mt-3">
      <div className="flex h-1.5 gap-[3px]">
        {bands.map(([a, b, c]) => (
          <span key={a} className="h-full rounded-full" style={{ width: `${b - a}%`, background: `color-mix(in srgb, ${c} ${score >= a ? 70 : 18}%, transparent)` }} />
        ))}
      </div>
      <motion.span
        className="absolute -top-1 size-3.5 -translate-x-1/2 rounded-full border-2 border-surface shadow"
        style={{ background: decisionColor(scoreDecision(score)) }}
        initial={{ left: '0%' }}
        animate={{ left: `${Math.min(100, score)}%` }}
        transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
      />
      <div className="tabular mt-1.5 flex justify-between text-[10px] text-faint">
        <span>0</span>
        <span>30</span>
        <span>60</span>
        <span>80</span>
        <span>100</span>
      </div>
    </div>
  )
}

function AccChip({ id }: { id: string }) {
  const { inspect } = useConsole()
  const s = engine.accountScore(id)
  return (
    <button
      onClick={() => inspect({ type: 'account', id })}
      className="inline-flex items-center gap-1.5 rounded-[7px] border border-line-strong bg-surface px-2 py-1 font-mono text-[11.5px] text-ink transition-colors hover:bg-hover"
    >
      <span className="size-1.5 rounded-full" style={{ background: s >= 30 ? decisionColor(scoreDecision(s)) : 'var(--faint)' }} />
      {id}
    </button>
  )
}

function Json({ value }: { value: unknown }) {
  const text = JSON.stringify(value, null, 2)
  const html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/("[^"]+")(\s*:)/g, '<span style="color:var(--muted)">$1</span>$2')
    .replace(/: ("[^"]*")/g, ': <span style="color:var(--ink)">$1</span>')
    .replace(/: (-?\d+\.?\d*)/g, ': <span style="color:var(--monitor)">$1</span>')
    .replace(/: (null|true|false)/g, ': <span style="color:var(--review)">$1</span>')
  return <pre className="scrollbar-thin max-h-[300px] overflow-auto rounded-[10px] border border-line bg-inset p-3 font-mono text-[11px] leading-[1.55] text-ink-2" dangerouslySetInnerHTML={{ __html: html }} />
}

function Actions({ children }: { children: React.ReactNode }) {
  return (
    <motion.div variants={blurIn} className="flex flex-wrap gap-2 border-t border-line pt-4">
      {children}
    </motion.div>
  )
}
function Btn({ onClick, children, primary }: { onClick(): void; children: React.ReactNode; primary?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex h-8 items-center gap-1.5 rounded-[8px] px-3 text-[12.5px] font-medium transition-colors ${primary ? 'bg-primary text-primary-fg hover:opacity-90' : 'border border-line-strong bg-surface text-ink hover:bg-hover'}`}
    >
      {children}
    </button>
  )
}

/* ---------------------------- Transaction ---------------------------- */
function TxnView({ id, inline }: { id: string; inline?: boolean }) {
  const { focusGraph, go, view, closeDrawer } = useConsole()
  const r = engine.record(id)
  if (!r) return <p className="py-10 text-center text-[12.5px] text-muted">Transaction left the retained window.</p>
  const ev = r.evaluation
  const w = engine.settings.weights
  const wSum = Object.values(w).reduce((a, b) => a + b, 0) || 1
  const cases = engine.investigations.filter((i) => i.transactionIds.includes(id))
  const trace = () => {
    if (!ev) return
    if (!inline) closeDrawer()
    if (view !== 'overview' && view !== 'network') go('network')
    focusGraph(ev.involvedAccounts, ev.evidenceTransactionIds.concat(id))
  }
  return (
    <>
      <motion.div variants={blurIn} className="rounded-[12px] border border-line bg-inset p-3.5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[13px] text-ink">{id}</span>
          {ev && <DecisionBadge decision={ev.decision} size="md" />}
          <span className="ml-auto">
            <StatusText status={r.status} />
          </span>
        </div>
        <div className="mt-3 flex items-end gap-2">
          <span className="text-[34px] font-medium leading-none tracking-[-0.03em]" style={{ color: ev ? decisionColor(ev.decision) : 'var(--muted)' }}>
            {ev ? ev.riskScore.toFixed(1) : '…'}
          </span>
          <span className="pb-1 text-[12px] text-muted">/ 100 risk</span>
          <span className="tabular ml-auto pb-1 text-[12px] text-muted">{ev ? `${formatMs(ev.evalMs)} ms` : 'evaluating'}</span>
        </div>
        {ev && <Gauge score={ev.riskScore} />}
      </motion.div>

      <Block title="Transfer">
        <div className="flex flex-wrap items-center gap-2">
          <AccChip id={r.event.senderId} />
          <ArrowRight className="size-3.5 text-faint" />
          <AccChip id={r.event.receiverId} />
          <span className="tabular ml-auto text-[15px] font-medium text-ink">{formatINR(r.event.amount, true)}</span>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
          <Stat k="Event time" v={clock(r.event.eventTimestamp)} />
          <Stat k="Amount (paise)" v={r.event.amount.toLocaleString('en-IN')} mono />
          <Stat k="Source" v={r.scenario === 'NORMAL' ? 'Organic sim' : r.scenario === 'EXTERNAL' ? 'External' : 'Scenario'} />
        </div>
      </Block>

      {ev && (
        <Block title="Triggered patterns">
          <div className="flex flex-wrap gap-1.5">{ev.patterns.length ? ev.patterns.map((p) => <PatternBadge key={p} pattern={p} />) : <span className="text-[12px] text-muted">None — no corroborating graph signals</span>}</div>
        </Block>
      )}

      {ev && (
        <Block title="Weighted contribution" right={<span className="font-mono text-[10.5px] text-faint">R = Σ wᵢ·sᵢ</span>}>
          <div className="space-y-2">
            {SIGNALS.map(({ key, label }) => {
              const s = ev.signals[key]
              const pts = ((w[key] * s) / wSum) * 100
              return (
                <div key={key} className="grid grid-cols-[96px_1fr_40px] items-center gap-3">
                  <span className="font-mono text-[11px] text-ink-2">
                    {label} <span className="text-faint">{w[key].toFixed(2)}</span>
                  </span>
                  <span className="h-1.5 overflow-hidden rounded-full bg-inset">
                    <motion.span
                      className="block h-full rounded-full"
                      style={{ background: s >= 0.5 ? decisionColor(ev.decision) : 'var(--faint)' }}
                      initial={{ width: 0 }}
                      animate={{ width: `${s * 100}%` }}
                      transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
                    />
                  </span>
                  <span className="tabular text-right text-[11.5px] text-ink">+{pts.toFixed(1)}</span>
                </div>
              )
            })}
          </div>
        </Block>
      )}

      {ev && (
        <Block title="Evidence" right={<span className="font-mono text-[10.5px] text-muted">{ev.source}</span>}>
          <Json
            value={{
              transactionId: id,
              riskScore: ev.riskScore,
              decision: ev.decision,
              patterns: ev.patterns,
              evidence: ev.evidence,
              involvedAccounts: ev.involvedAccounts,
              evidenceTransactionIds: ev.evidenceTransactionIds.slice(0, 8),
              processingStatus: ev.processingStatus,
              modelVersion: ev.modelVersion,
            }}
          />
        </Block>
      )}

      <Block title="Lifecycle">
        <Lifecycle r={r} />
      </Block>

      <Actions>
        {ev && (
          <Btn primary onClick={trace}>
            <Network className="size-3.5" /> Show on graph
          </Btn>
        )}
        {cases.length > 0 && (
          <Btn onClick={() => (closeDrawer(), go('investigations'))}>
            <FolderSearch className="size-3.5" /> {cases[0].id}
          </Btn>
        )}
      </Actions>
    </>
  )
}

function Stat({ k, v, mono }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <div className="rounded-[8px] border border-line px-2.5 py-2">
      <p className="text-[10.5px] text-muted">{k}</p>
      <p className={`tabular mt-0.5 truncate text-[12.5px] text-ink ${mono ? 'font-mono text-[11.5px]' : ''}`}>{v}</p>
    </div>
  )
}

function Lifecycle({ r }: { r: TxnRecord }) {
  const ev = r.evaluation
  const steps: { label: string; meta: string; done: boolean; tone?: string }[] = [
    { label: 'PENDING', meta: 'Candidate edge · not in graph', done: true },
    { label: 'EVALUATED', meta: ev ? `${formatMs(ev.evalMs)} ms · ${ev.processingStatus}` : 'In progress', done: !!ev },
    {
      label: r.status === 'FAILED' ? 'FAILED' : r.status === 'PENDING' ? 'OUTCOME' : 'SUCCESS',
      meta: r.status === 'FAILED' ? 'Discarded · no edge' : r.status === 'PENDING' ? 'Awaiting payment outcome' : 'XADD transactions',
      done: r.status !== 'PENDING',
      tone: r.status === 'FAILED' ? 'var(--faint)' : undefined,
    },
  ]
  if (r.status !== 'FAILED') steps.push({ label: 'CONFIRMED', meta: r.confirmedAt ? `Graph worker · ${clock(r.confirmedAt)}` : 'Queued in stream', done: !!r.confirmedAt })
  if (r.status === 'REVERSED') steps.push({ label: 'REVERSED', meta: 'Compensating update', done: true, tone: 'var(--review)' })
  return (
    <ol className="relative space-y-3 pl-5">
      <span className="absolute bottom-1.5 left-[5px] top-1.5 w-px bg-line-strong" />
      {steps.map((s) => (
        <li key={s.label} className="relative">
          <span
            className={`absolute -left-5 top-[3px] size-[11px] rounded-full border-2 ${s.done ? '' : 'border-dashed bg-surface'}`}
            style={{ borderColor: s.done ? (s.tone ?? 'var(--ink)') : 'var(--faint)', background: s.done ? (s.tone ?? 'var(--ink)') : undefined }}
          />
          <p className={`font-mono text-[11.5px] ${s.done ? 'text-ink' : 'text-muted'}`}>{s.label}</p>
          <p className="text-[11px] text-muted">{s.meta}</p>
        </li>
      ))}
    </ol>
  )
}

/* ---------------------------- Account ---------------------------- */
function AccountView({ id, inline }: { id: string; inline?: boolean }) {
  const { focusGraph, inspect, go, view, closeDrawer } = useConsole()
  const acc = engine.accounts.get(id)
  const risk = engine.risk.get(id)
  const score = engine.accountScore(id)
  const txns = engine.accountTxns(id, 300)
  const confirmed = txns.filter((t) => t.status === 'SUCCESS')
  const inT = confirmed.filter((t) => t.event.receiverId === id)
  const outT = confirmed.filter((t) => t.event.senderId === id)
  const inAmt = inT.reduce((a, t) => a + t.event.amount, 0)
  const outAmt = outT.reduce((a, t) => a + t.event.amount, 0)
  const peers = new Map<string, { in: number; out: number }>()
  for (const t of txns) {
    const other = t.event.senderId === id ? t.event.receiverId : t.event.senderId
    const p = peers.get(other) ?? { in: 0, out: 0 }
    if (t.event.senderId === id) p.out++
    else p.in++
    peers.set(other, p)
  }
  const history = txns
    .filter((t) => t.evaluation)
    .map((t) => t.evaluation!.riskScore)
    .reverse()
  const flagged = txns.filter((t) => t.evaluation && t.evaluation.decision !== 'ALLOW')
  const cases = engine.investigations.filter((i) => i.accounts.includes(id))
  const trace = () => {
    if (!inline) closeDrawer()
    if (view !== 'overview' && view !== 'network') go('network')
    focusGraph([id, ...peers.keys()], txns.slice(0, 60).map((t) => t.event.transactionId))
  }
  if (!acc) return <p className="py-10 text-center text-[12.5px] text-muted">Unknown account.</p>
  return (
    <>
      <motion.div variants={blurIn} className="rounded-[12px] border border-line bg-inset p-3.5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[14px] text-ink">{id}</span>
          <span className="rounded-[5px] border border-line-strong bg-surface px-1.5 py-[1px] text-[10.5px] text-ink-2">{acc.kind}</span>
          <span className="rounded-[5px] bg-allow-bg px-1.5 py-[1px] text-[10.5px] text-allow">{acc.accountStatus}</span>
          <span className="ml-auto text-[11.5px] text-muted">{acc.accountAgeDays}d old</span>
        </div>
        <div className="mt-3 flex items-end gap-2">
          <span className="text-[34px] font-medium leading-none tracking-[-0.03em]" style={{ color: decisionColor(scoreDecision(score)) }}>
            {score.toFixed(1)}
          </span>
          <span className="pb-1 text-[12px] text-muted">account risk · decays over {engine.settings.windowSec}s</span>
        </div>
        <Gauge score={score} />
      </motion.div>

      <Block title="Activity in window">
        <div className="grid grid-cols-2 gap-2">
          <Stat k={`Incoming · ${inT.length}`} v={formatINRCompact(inAmt)} />
          <Stat k={`Outgoing · ${outT.length}`} v={formatINRCompact(outAmt)} />
          <Stat k="Counterparties" v={peers.size} />
          <Stat k="Out / In" v={inAmt ? (outAmt / inAmt).toFixed(2) : '—'} />
        </div>
        {acc.accountAgeDays < 30 && <p className="mt-2 text-[11px] text-muted">Young account — contextual only, not evidence on its own.</p>}
      </Block>

      <Block title="Detected patterns">
        <div className="flex flex-wrap gap-1.5">{risk?.patterns.length ? risk.patterns.map((p) => <PatternBadge key={p} pattern={p} />) : <span className="text-[12px] text-muted">None</span>}</div>
      </Block>

      {history.length > 1 && (
        <Block title="Risk history" right={<span className="text-[11px] text-muted">{history.length} evaluations</span>}>
          <div className="rounded-[10px] border border-line px-2 py-2">
            <Sparkline data={history} className="h-12 w-full" stroke="var(--ink-2)" />
          </div>
        </Block>
      )}

      <Block title="Connected accounts" right={<span className="text-[11px] text-muted">{peers.size}</span>}>
        <div className="flex flex-wrap gap-1.5">
          {[...peers.entries()].slice(0, 18).map(([p, c]) => (
            <span key={p} className="inline-flex items-center gap-1">
              <AccChip id={p} />
              <span className="tabular text-[10.5px] text-muted">
                {c.in ? `↓${c.in}` : ''}
                {c.out ? `↑${c.out}` : ''}
              </span>
            </span>
          ))}
        </div>
      </Block>

      <Block title="Recent activity" right={flagged.length ? <span className="text-[11px] text-escalate">{flagged.length} flagged</span> : undefined}>
        <ul className="divide-y divide-line rounded-[10px] border border-line">
          {txns.slice(0, 8).map((t) => {
            const out = t.event.senderId === id
            return (
              <li key={t.event.transactionId}>
                <button onClick={() => inspect({ type: 'txn', id: t.event.transactionId })} className="flex w-full items-center gap-2.5 px-2.5 py-2 text-left transition-colors hover:bg-hover">
                  <span className={`grid size-5 place-items-center rounded-[5px] ${out ? 'bg-inset text-ink-2' : 'bg-inset text-muted'}`}>
                    {out ? <ArrowUpRight className="size-3" /> : <ArrowDownLeft className="size-3" />}
                  </span>
                  <span className="font-mono text-[11.5px] text-ink">{out ? t.event.receiverId : t.event.senderId}</span>
                  <span className="tabular text-[11px] text-muted">{ago(t.event.eventTimestamp, engine.now())}</span>
                  <span className="tabular ml-auto text-[12px] text-ink">{formatINR(t.event.amount)}</span>
                  {t.evaluation && (
                    <span className="w-9 text-right text-[11.5px]">
                      <ScoreText score={t.evaluation.riskScore} />
                    </span>
                  )}
                </button>
              </li>
            )
          })}
          {!txns.length && <li className="px-3 py-4 text-center text-[12px] text-muted">No retained activity</li>}
        </ul>
      </Block>

      {flagged[0]?.evaluation && (
        <Block title="Supporting evidence">
          <p className="mb-2 text-[11.5px] text-muted">
            Strongest: <span className="font-mono text-ink-2">{flagged.slice().sort((a, b) => b.evaluation!.riskScore - a.evaluation!.riskScore)[0].event.transactionId}</span> ·{' '}
            {flagged[0].evaluation.patterns.map((p) => PATTERN_LABEL[p]).join(', ') || 'context'}
          </p>
          <Json value={flagged.slice().sort((a, b) => b.evaluation!.riskScore - a.evaluation!.riskScore)[0].evaluation!.evidence} />
        </Block>
      )}

      <Actions>
        <Btn primary onClick={trace}>
          <Network className="size-3.5" /> Trace on graph
        </Btn>
        {cases.length > 0 && (
          <Btn onClick={() => (closeDrawer(), go('investigations'))}>
            <FolderSearch className="size-3.5" /> {cases[0].id}
          </Btn>
        )}
      </Actions>
    </>
  )
}
