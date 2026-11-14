import { motion } from 'motion/react'
import { ArrowRight, GitBranch, Pause, Play, Radio, Repeat, RotateCcw, Split, Workflow, ArrowUpRight, Sparkles } from 'lucide-react'
import { engine } from '../../engine/SimulationEngine'
import { SCENARIOS } from '../../engine/scenarios'
import type { ScenarioId } from '../../engine/types'
import { blurIn, stagger } from '../ui/Reveal'
import { useEngine } from './ConsoleContext'
import { Segmented } from './Panels'

const ICON: Record<ScenarioId, React.ReactNode> = {
  MULE_NETWORK: <Workflow className="size-3.5" />,
  FAN_OUT: <Split className="size-3.5" />,
  PASS_THROUGH: <ArrowUpRight className="size-3.5" />,
  CYCLE: <Repeat className="size-3.5" />,
  MULTI_HOP: <GitBranch className="size-3.5" />,
}

/** Zone 3 — demo scenario triggers (synthetic data only). */
export default function SimulationDeck() {
  const { running } = useEngine()
  const active = engine.scenarios
  return (
    <motion.div initial="hidden" animate="show" variants={stagger(0.05)} className="flex h-full flex-col">
      <motion.div variants={blurIn} className="relative mx-4 mt-4 h-[150px] overflow-hidden rounded-[12px] border border-line bg-inset-2">
        <div className="absolute inset-y-0 left-1/2 w-px -translate-x-[60px] bg-line" />
        <div className="absolute inset-y-0 left-1/2 w-px translate-x-[60px] bg-line" />
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-[34px] bg-line" />
        <div className="absolute inset-x-0 top-1/2 h-px translate-y-[34px] bg-line" />
        <div className="absolute left-1/2 top-1/2 grid size-14 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-line bg-surface shadow-pop">
          <Sparkles className="size-5 text-ink" />
          {running && <span className="anim-ping absolute inset-0 rounded-full border border-line-strong" />}
        </div>
      </motion.div>

      <motion.div variants={blurIn} className="px-4 pt-4">
        <p className="text-[14px] font-medium text-ink">Run a scenario</p>
        <p className="mt-0.5 text-[12px] text-muted">Synthetic UPI traffic. Never real payments.</p>
      </motion.div>

      <motion.div variants={blurIn} className="mx-4 mt-3 flex flex-wrap items-center gap-2 rounded-[10px] border border-line p-2">
        <button
          onClick={() => engine.toggle()}
          className="inline-flex h-7 items-center gap-1.5 rounded-[7px] bg-primary px-2.5 text-[12px] font-medium text-primary-fg transition-opacity hover:opacity-90"
        >
          {running ? <Pause className="size-3" /> : <Play className="size-3" />}
          {running ? 'Pause' : 'Start'}
        </button>
        <label className="inline-flex cursor-pointer items-center gap-2 text-[12px] text-ink-2">
          <span className="relative inline-flex">
            <input type="checkbox" className="peer sr-only" checked={engine.normalTraffic} onChange={(e) => engine.setNormalTraffic(e.target.checked)} />
            <span className="h-4 w-7 rounded-full bg-line-strong transition-colors peer-checked:bg-allow" />
            <span className="absolute left-0.5 top-0.5 size-3 rounded-full bg-surface shadow transition-transform peer-checked:translate-x-3" />
          </span>
          <Radio className="size-3 text-muted" /> Normal traffic
        </label>
        <span className="ml-auto">
          <Segmented
            label="Rate"
            value={engine.trafficRate}
            onChange={(v) => engine.setTrafficRate(v)}
            options={[
              { value: 1.1, label: '1×' },
              { value: 2.2, label: '2×' },
              { value: 4.4, label: '4×' },
            ]}
          />
        </span>
      </motion.div>

      <div className="mt-3 space-y-1.5 px-4">
        {SCENARIOS.map((s) => {
          const run = active.find((a) => a.id === s.id && a.done < a.total)
          return (
            <motion.button
              variants={blurIn}
              key={s.id}
              onClick={() => engine.triggerScenario(s.id)}
              className="group relative flex w-full items-center gap-3 overflow-hidden rounded-[10px] border border-line bg-inset-2 px-3 py-2.5 text-left transition-colors hover:border-line-strong hover:bg-hover"
            >
              <span className="grid size-7 place-items-center rounded-[7px] border border-line bg-surface text-ink-2">{ICON[s.id]}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-[12.5px] font-medium text-ink">{s.id === 'MULE_NETWORK' ? 'Trigger Mule Network' : `Trigger ${s.label}`}</span>
                <span className="block truncate text-[11.5px] text-muted">{s.short}</span>
              </span>
              {run ? (
                <span className="tabular text-[11px] text-ink-2">
                  {run.done}/{run.total}
                </span>
              ) : (
                <ArrowRight className="size-3.5 text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-ink" />
              )}
              {run && (
                <motion.span className="absolute bottom-0 left-0 h-[2px] bg-primary" initial={false} animate={{ width: `${(run.done / run.total) * 100}%` }} transition={{ duration: 0.4 }} />
              )}
            </motion.button>
          )
        })}
      </div>

      <motion.div variants={blurIn} className="mt-auto p-4">
        {active.length > 0 && (
          <div className="mb-3 rounded-[10px] border border-line p-2.5">
            <p className="mb-1.5 text-[11.5px] text-muted">Recent runs</p>
            {active.slice(0, 3).map((a) => (
              <div key={a.runId} className="flex items-center gap-2 py-0.5 text-[11.5px]">
                <span className={`size-1.5 rounded-full ${a.done < a.total ? 'bg-review' : 'bg-allow'}`} />
                <span className="text-ink-2">{a.label}</span>
                <span className="tabular ml-auto text-muted">
                  {a.done}/{a.total} · {a.accounts.length} accts
                </span>
              </div>
            ))}
          </div>
        )}
        <button
          onClick={() => engine.reset()}
          className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-[9px] border border-line-strong text-[12.5px] font-medium text-ink-2 transition-colors hover:border-escalate hover:text-escalate"
        >
          <RotateCcw className="size-3.5" /> Reset Graph
        </button>
      </motion.div>
    </motion.div>
  )
}
