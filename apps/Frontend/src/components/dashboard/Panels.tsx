import { useEffect, useRef } from 'react'
import { animate, motion } from 'motion/react'
import { Gauge, ShieldExclamationPoint, Timer, Users } from 'lucide-react'
import { engine } from '../../engine/SimulationEngine'
import { fmtInt, formatMs } from '../../lib/format'
import { blurIn } from '../ui/Reveal'
import { useEngine } from './ConsoleContext'

/** Tweened number written straight to the DOM (no React re-render per frame). */
export function Num({ value, format = (v) => fmtInt(Math.round(v)) }: { value: number; format?: (v: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const prev = useRef(value)
  useEffect(() => {
    const from = prev.current
    prev.current = value
    const c = animate(from, value, {
      duration: 0.6,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => {
        if (ref.current) ref.current.textContent = format(v)
      },
    })
    return () => c.stop()
  }, [value])
  return (
    <span ref={ref} className="tabular">
      {format(value)}
    </span>
  )
}

export function Sparkline({ data, className = '', stroke = 'var(--faint)' }: { data: number[]; className?: string; stroke?: string }) {
  if (data.length < 2) return <svg className={className} />
  const max = Math.max(...data) || 1
  const min = Math.min(...data)
  const span = max - min || 1
  const pts = data.map((v, i) => [(i / (data.length - 1)) * 100, 28 - ((v - min) / span) * 24])
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
  const last = pts[pts.length - 1]
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className={className} aria-hidden>
      <path d={d} fill="none" stroke={stroke} strokeWidth="1.4" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r="1.6" fill="var(--ink)" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

export function Card({ children, className = '', ...rest }: React.ComponentProps<typeof motion.section>) {
  return (
    <motion.section variants={blurIn} className={`rounded-[14px] border border-line bg-surface shadow-card ${className}`} {...rest}>
      {children}
    </motion.section>
  )
}

export function CardHead({ title, sub, right }: { title: string; sub?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pb-3 pt-3.5">
      <h2 className="text-[14.5px] font-medium tracking-[-0.005em] text-ink">{title}</h2>
      {sub && <span className="text-[12px] text-muted">{sub}</span>}
      {right && <div className="ml-auto flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  )
}

export function Segmented<T extends string | number>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange(v: NoInfer<T>): void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex h-7 items-center rounded-[8px] bg-inset p-0.5">
      {options.map((o) => (
        <button
          key={String(o.value)}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={`relative h-6 rounded-[6px] px-2 text-[11.5px] transition-colors duration-200 ${o.value === value ? 'text-ink' : 'text-muted hover:text-ink-2'}`}
        >
          {o.value === value && <motion.span layoutId={`seg-${label}`} className="absolute inset-0 rounded-[6px] bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.08)]" transition={{ type: 'spring', stiffness: 500, damping: 38 }} />}
          <span className="relative">{o.label}</span>
        </button>
      ))}
    </div>
  )
}

export function IconButton({ label, onClick, children, active }: { label: string; onClick(): void; children: React.ReactNode; active?: boolean }) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`grid size-7 place-items-center rounded-[8px] border transition-colors duration-200 ${active ? 'border-primary bg-primary text-primary-fg' : 'border-line-strong bg-surface text-ink-2 hover:bg-hover'}`}
    >
      {children}
    </button>
  )
}

function DashedDot() {
  return <span className="size-3 rounded-full border border-dashed border-faint" />
}

function Kpi({ icon, label, value, unit, foot, spark }: { icon: React.ReactNode; label: string; value: React.ReactNode; unit?: string; foot: React.ReactNode; spark?: number[] }) {
  return (
    <Card className="p-1.5">
      <div className="relative overflow-hidden rounded-[10px] bg-inset px-3.5 pb-3 pt-3">
        <div className="flex items-center gap-2.5">
          <span className="grid size-7 place-items-center rounded-[7px] border border-line bg-surface text-ink">{icon}</span>
          <span className="text-[13px] text-ink-2">{label}</span>
        </div>
        <div className="mt-1.5 flex items-end justify-between pl-[38px]">
          <span className="text-[26px] font-medium leading-none tracking-[-0.02em] text-ink">
            {value}
            {unit && <span className="ml-1 text-[12.5px] font-normal tracking-normal text-muted">{unit}</span>}
          </span>
          {spark && <Sparkline data={spark} className="h-7 w-20 max-sm:hidden" />}
        </div>
      </div>
      <div className="flex items-center justify-between px-2 pb-0.5 pt-1.5 text-[11.5px]">
        <span className="flex items-center gap-1.5">
          <DashedDot />
          {foot}
        </span>
        <DashedDot />
      </div>
    </Card>
  )
}

/** Zone 1 — low-latency telemetry. All values are measured from the running engine. */
export function TelemetryKpis() {
  useEngine()
  const m = engine.metrics()
  const open = engine.investigations.filter((i) => i.status !== 'CLOSED').length
  const live = engine.connection.mode === 'REMOTE'
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <Kpi
        icon={<Timer className="size-3.5" />}
        label="p95 Eval Latency"
        value={<Num value={m.p95} format={formatMs} />}
        unit="ms"
        spark={m.latencyHistory}
        foot={
          <>
            <span className={m.p95 < 100 ? 'text-allow' : 'text-escalate'}>{m.p95 < 100 ? '< 100 ms target' : 'Over target'}</span>
            <span className="text-muted max-sm:hidden">· {live ? 'remote' : 'in-browser'}</span>
          </>
        }
      />
      <Kpi
        icon={<Gauge className="size-3.5" />}
        label="Throughput"
        value={<Num value={m.tps} format={(v) => v.toFixed(1)} />}
        unit="TXN/s"
        spark={m.tpsHistory}
        foot={
          <span className="text-muted">
            <span className="tabular text-ink-2">{fmtInt(m.evaluated)}</span> evaluated
          </span>
        }
      />
      <Kpi
        icon={<ShieldExclamationPoint className="size-3.5" />}
        label="Flagged"
        value={<Num value={m.flagged} />}
        unit="txns"
        foot={
          <span className="text-muted">
            <span className={`tabular ${m.decisions.ESCALATE ? 'text-escalate' : 'text-ink-2'}`}>{m.decisions.ESCALATE}</span> escalated ·{' '}
            <span className="tabular text-ink-2">{m.decisions.REVIEW}</span> review
          </span>
        }
      />
      <Kpi
        icon={<Users className="size-3.5" />}
        label="Under Investigation"
        value={<Num value={m.underInvestigation} />}
        unit="accounts"
        foot={
          <span className="text-muted">
            <span className={`tabular ${m.pendingReviews ? 'text-review' : 'text-ink-2'}`}>{m.pendingReviews}</span> pending review · {open} open
          </span>
        }
      />
    </div>
  )
}

/** Hairline tick strip (reference motif) — one tick per recent evaluation, coloured by decision. */
export function EventTicker({ count = 140 }: { count?: number }) {
  useEngine()
  const ticks = engine.order.slice(0, count)
  return (
    <div className="flex h-5 items-end justify-end gap-[3px] overflow-hidden px-4 pb-3" aria-hidden>
      {ticks
        .slice()
        .reverse()
        .map((id) => {
          const d = engine.records.get(id)?.evaluation?.decision
          const c = !d || d === 'ALLOW' ? 'var(--line-strong)' : `var(--${d.toLowerCase()})`
          return <span key={id} className="w-px shrink-0 rounded-full transition-colors" style={{ height: d && d !== 'ALLOW' ? 12 : 8, background: c }} />
        })}
    </div>
  )
}
