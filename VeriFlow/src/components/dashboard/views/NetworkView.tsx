import { useState } from 'react'
import { MousePointerClick } from 'lucide-react'
import { engine } from '../../../engine/SimulationEngine'
import GraphPanel from '../GraphPanel'
import RiskInspector from '../RiskInspector'
import type { GraphSelection } from '../CytoscapeGraph'
import { Card, CardHead } from '../Panels'
import { PageHead } from './Common'
import { SCENARIOS } from '../../../engine/scenarios'
import { useEngine } from '../ConsoleContext'

export default function NetworkView() {
  useEngine()
  const [sel, setSel] = useState<GraphSelection>(null)
  return (
    <>
      <PageHead
        title="Live Network"
        sub="Click any account or transfer to inspect its neighbourhood."
        right={
          <div className="flex flex-wrap gap-1.5">
            {SCENARIOS.map((s) => (
              <button
                key={s.id}
                onClick={() => engine.triggerScenario(s.id)}
                className="h-8 rounded-[8px] border border-line-strong bg-surface px-2.5 text-[12px] text-ink-2 transition-colors hover:bg-hover"
              >
                {s.label}
              </button>
            ))}
          </div>
        }
      />
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_400px]">
        <GraphPanel height="max(520px, calc(100dvh - 300px))" onSelect={setSel} title="Transaction Network" searchable />
        <Card className="flex max-h-[calc(100dvh-140px)] min-h-[420px] flex-col overflow-hidden xl:sticky xl:top-[72px]">
          <CardHead title="Inspector" sub={sel ? (sel.type === 'account' ? 'Account' : 'Transaction') : undefined} />
          <div className="scrollbar-thin flex-1 overflow-y-auto border-t border-line">
            {sel ? (
              <RiskInspector target={sel} inline />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 p-10 text-center">
                <span className="grid size-12 place-items-center rounded-full border border-dashed border-faint text-muted">
                  <MousePointerClick className="size-5" />
                </span>
                <p className="text-[13px] text-ink-2">Select a node or edge</p>
                <p className="text-[12px] text-muted">Neighbourhood highlights up to 4 hops.</p>
              </div>
            )}
          </div>
        </Card>
      </div>
    </>
  )
}
