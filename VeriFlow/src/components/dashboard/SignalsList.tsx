import { AnimatePresence, motion } from 'motion/react'
import { ArrowRight, GitBranch, Merge, Repeat, Split, ArrowUpRight } from 'lucide-react'
import { engine } from '../../engine/SimulationEngine'
import type { FraudSignal, Pattern } from '../../engine/types'
import { ago } from '../../lib/format'
import { DecisionBadge, PATTERN_LABEL, decisionColor } from '../ui/Badges'
import { EASE } from '../ui/Reveal'

export const PATTERN_ICON: Record<Pattern, React.ReactNode> = {
  FAN_OUT: <Split className="size-3.5" />,
  FAN_IN: <Merge className="size-3.5" />,
  RAPID_PASS_THROUGH: <ArrowUpRight className="size-3.5" />,
  CYCLE: <Repeat className="size-3.5" />,
  MULTI_HOP: <GitBranch className="size-3.5" />,
}

export default function SignalsList({ signals, onOpen, onTrace }: { signals: FraudSignal[]; onOpen(s: FraudSignal): void; onTrace?(s: FraudSignal): void }) {
  const now = engine.now()
  return (
    <ul className="space-y-1">
      <AnimatePresence initial={false}>
        {signals.map((s) => (
          <motion.li
            key={s.id}
            layout="position"
            initial={{ opacity: 0, y: -6, filter: 'blur(6px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.45, ease: EASE }}
          >
            <div
              role="button"
              tabIndex={0}
              onClick={() => onOpen(s)}
              onKeyDown={(e) => e.key === 'Enter' && onOpen(s)}
              className="group flex w-full items-start gap-3 rounded-[10px] px-2.5 py-2.5 text-left transition-colors hover:bg-hover"
            >
              <span
                className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-[7px]"
                style={{ background: `color-mix(in srgb, ${decisionColor(s.decision)} 14%, transparent)`, color: decisionColor(s.decision) }}
              >
                {PATTERN_ICON[s.pattern]}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className="text-[13px] font-medium text-ink">{PATTERN_LABEL[s.pattern]}</span>
                  {s.patterns.length > 1 && (
                    <span className="rounded-[5px] bg-inset px-1.5 py-[1px] text-[10.5px] text-muted" title={s.patterns.join(' · ')}>
                      +{s.patterns.length - 1}
                    </span>
                  )}
                  <span className="tabular text-[12px] font-medium" style={{ color: decisionColor(s.decision) }}>
                    {s.riskScore.toFixed(1)}
                  </span>
                  <span className="ml-auto">
                    <DecisionBadge decision={s.decision} />
                  </span>
                </span>
                <span className="mt-0.5 block truncate font-mono text-[11px] text-ink-2">{s.summary}</span>
                <span className="mt-1 flex items-center gap-2 text-[11px] text-muted">
                  <span className="font-mono">{s.transactionId}</span>· {s.involvedAccounts.length} accounts · {ago(s.detectedAt, now)}
                  {onTrace && (
                    <button
                      onClick={(e) => (e.stopPropagation(), onTrace(s))}
                      className="ml-auto inline-flex items-center gap-1 text-muted opacity-0 transition-opacity hover:text-ink group-hover:opacity-100 focus:opacity-100"
                    >
                      Trace <ArrowRight className="size-3" />
                    </button>
                  )}
                </span>
              </span>
            </div>
          </motion.li>
        ))}
      </AnimatePresence>
      {!signals.length && (
        <li className="flex flex-col items-center gap-2 py-10 text-center">
          <span className="size-8 rounded-full border border-dashed border-faint" />
          <span className="text-[12.5px] text-muted">No signals yet</span>
          <span className="text-[11.5px] text-faint">Trigger a scenario from the simulator</span>
        </li>
      )}
    </ul>
  )
}
