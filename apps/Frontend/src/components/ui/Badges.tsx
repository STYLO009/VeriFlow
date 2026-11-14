import type { Decision, Pattern, TxnStatus } from '../../engine/types'

const DECISION_CLS: Record<Decision, string> = {
  ALLOW: 'bg-allow-bg text-allow',
  MONITOR: 'bg-monitor-bg text-monitor',
  REVIEW: 'bg-review-bg text-review',
  ESCALATE: 'bg-escalate-bg text-escalate',
}
const DECISION_GLYPH: Record<Decision, string> = { ALLOW: '●', MONITOR: '◐', REVIEW: '▲', ESCALATE: '■' }

export function DecisionBadge({ decision, size = 'sm' }: { decision: Decision; size?: 'sm' | 'md' }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-[5px] font-medium tracking-[0.01em] ${DECISION_CLS[decision]} ${
        size === 'md' ? 'px-2 py-[3px] text-[11.5px]' : 'px-1.5 py-[2px] text-[10.5px]'
      }`}
    >
      <span aria-hidden className="text-[7px] leading-none">
        {DECISION_GLYPH[decision]}
      </span>
      {decision}
    </span>
  )
}

export const decisionColor = (d: Decision) => `var(--${d.toLowerCase()})`
export const scoreDecision = (s: number): Decision => (s >= 80 ? 'ESCALATE' : s >= 60 ? 'REVIEW' : s >= 30 ? 'MONITOR' : 'ALLOW')

export function ScoreText({ score }: { score: number }) {
  return (
    <span className="tabular font-medium" style={{ color: decisionColor(scoreDecision(score)) }}>
      {score.toFixed(1)}
    </span>
  )
}

export const PATTERN_LABEL: Record<Pattern, string> = {
  FAN_OUT: 'Fan-Out',
  FAN_IN: 'Fan-In',
  RAPID_PASS_THROUGH: 'Pass-Through',
  CYCLE: 'Cycle',
  MULTI_HOP: 'Multi-Hop',
}

export function PatternBadge({ pattern }: { pattern: Pattern }) {
  return (
    <span className="inline-flex items-center rounded-[5px] border border-line-strong bg-surface px-1.5 py-[1px] font-mono text-[10px] tracking-tight text-ink-2">
      {pattern}
    </span>
  )
}

const STATUS_CLS: Record<TxnStatus, string> = {
  PENDING: 'text-muted',
  SUCCESS: 'text-ink-2',
  FAILED: 'text-faint line-through',
  REVERSED: 'text-review',
}
export function StatusText({ status }: { status: TxnStatus }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-[11.5px] ${STATUS_CLS[status]}`}>
      <span
        className={`size-1.5 rounded-full ${
          status === 'PENDING' ? 'border border-dashed border-muted' : status === 'SUCCESS' ? 'bg-allow' : status === 'REVERSED' ? 'bg-review' : 'bg-faint'
        }`}
      />
      {status}
    </span>
  )
}
