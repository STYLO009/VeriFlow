import { useRef, useState } from 'react'
import { Crosshair, Filter, Maximize2, Minus, Pause, Play, Plus, RotateCcw, Search } from 'lucide-react'
import { engine } from '../../engine/SimulationEngine'
import { fmtInt, formatMs } from '../../lib/format'
import CytoscapeGraph, { type GraphHandle, type GraphLayout, type GraphSelection } from './CytoscapeGraph'
import { useConsole, useEngine } from './ConsoleContext'
import { Card, CardHead, IconButton, Segmented } from './Panels'

export default function GraphPanel({ height = 520, onSelect, title = 'Transaction Network', searchable }: { height?: number | string; onSelect?: (s: GraphSelection) => void; title?: string; searchable?: boolean }) {
  const { theme, focus, inspect } = useConsole()
  const [layout, setLayout] = useState<GraphLayout>('cola')
  const [windowSec, setWindow] = useState(60)
  const [hops, setHops] = useState(2)
  const [flagged, setFlagged] = useState(false)
  const [q, setQ] = useState('')
  const [miss, setMiss] = useState(false)
  const g = useRef<GraphHandle>(null)
  const handleSelect = onSelect ?? ((s: GraphSelection) => s && inspect(s))

  return (
    <Card className="flex min-w-0 flex-col overflow-hidden">
      <CardHead
        title={title}
        sub="Directed · weighted · temporal"
        right={
          <>
            {searchable && (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  const ok = g.current?.locate(q.trim().toUpperCase()) ?? false
                  setMiss(!ok)
                }}
                className="relative"
              >
                <Search className="pointer-events-none absolute left-2 top-1/2 size-3 -translate-y-1/2 text-muted" />
                <input
                  value={q}
                  onChange={(e) => (setQ(e.target.value), setMiss(false))}
                  placeholder="Locate ACC…"
                  aria-label="Locate account on graph"
                  className={`h-7 w-[124px] rounded-[8px] border bg-surface pl-6 pr-2 font-mono text-[11.5px] text-ink outline-none placeholder:font-sans placeholder:text-faint ${miss ? 'border-escalate' : 'border-line-strong focus:border-muted'}`}
                />
              </form>
            )}
            <Segmented
              label="Layout"
              value={layout}
              onChange={setLayout}
              options={[
                { value: 'cola', label: 'Force' },
                { value: 'concentric', label: 'Concentric' },
                { value: 'breadthfirst', label: 'Tree' },
              ]}
            />
            <Segmented
              label="Window"
              value={windowSec}
              onChange={setWindow}
              options={[
                { value: 30, label: '30s' },
                { value: 60, label: '60s' },
                { value: 300, label: '300s' },
              ]}
            />
          </>
        }
      />
      <div className="relative mx-1.5 overflow-hidden rounded-[10px] bg-inset-2 dot-grid-ink" style={{ height }}>
        <CytoscapeGraph ref={g} theme={theme} layout={layout} windowSec={windowSec} hops={hops} flaggedOnly={flagged} focus={focus} onSelect={handleSelect} className="absolute inset-0" />
        <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-1.5">
          <div className="pointer-events-auto flex items-center gap-1 rounded-[9px] border border-line bg-surface/90 p-1 shadow-card backdrop-blur">
            <IconButton label="Zoom out" onClick={() => g.current?.zoom(0.8)}>
              <Minus className="size-3.5" />
            </IconButton>
            <IconButton label="Fit to view" onClick={() => g.current?.fit()}>
              <Maximize2 className="size-3.5" />
            </IconButton>
            <IconButton label="Zoom in" onClick={() => g.current?.zoom(1.25)}>
              <Plus className="size-3.5" />
            </IconButton>
            <span className="mx-0.5 h-4 w-px bg-line" />
            <IconButton label="Re-run layout" onClick={() => g.current?.relayout()}>
              <RotateCcw className="size-3.5" />
            </IconButton>
            <IconButton label={flagged ? 'Show all edges' : 'Flagged edges only'} onClick={() => setFlagged(!flagged)} active={flagged}>
              <Filter className="size-3.5" />
            </IconButton>
          </div>
          <div className="pointer-events-auto flex items-center gap-1.5 self-start rounded-[9px] border border-line bg-surface/90 py-1 pl-2 pr-1 text-[11px] text-muted shadow-card backdrop-blur">
            <Crosshair className="size-3" /> Hops
            {[1, 2, 3, 4].map((h) => (
              <button
                key={h}
                onClick={() => setHops(h)}
                aria-pressed={h === hops}
                className={`tabular grid size-5 place-items-center rounded-[5px] text-[11px] transition-colors ${h === hops ? 'bg-primary text-primary-fg' : 'hover:bg-hover'}`}
              >
                {h}
              </button>
            ))}
          </div>
        </div>
        <StreamToggle />
        <Legend />
      </div>
      <GraphStatus windowSec={windowSec} />
    </Card>
  )
}

function StreamToggle() {
  const { running } = useEngine()
  return (
    <button
      onClick={() => engine.toggle()}
      className="absolute right-3 top-3 inline-flex h-8 items-center gap-1.5 rounded-full border border-line bg-surface/90 pl-2 pr-3 text-[12px] font-medium text-ink shadow-card backdrop-blur transition-colors hover:bg-surface"
    >
      <span className="relative grid size-4 place-items-center">
        {running && <span className="anim-ping absolute inset-0 rounded-full bg-allow" />}
        {running ? <Pause className="relative size-3" /> : <Play className="relative size-3" />}
      </span>
      {running ? 'Live' : 'Paused'}
    </button>
  )
}

function Legend() {
  const items: [string, string][] = [
    ['ALLOW', 'var(--faint)'],
    ['MONITOR', 'var(--monitor)'],
    ['REVIEW', 'var(--review)'],
    ['ESCALATE', 'var(--escalate)'],
  ]
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[9px] border border-line bg-surface/90 px-2.5 py-1.5 text-[10.5px] text-muted shadow-card backdrop-blur">
      {items.map(([l, c]) => (
        <span key={l} className="flex items-center gap-1.5">
          <span className="size-2 rounded-full" style={{ background: c }} />
          {l}
        </span>
      ))}
      <span className="flex items-center gap-1.5">
        <span className="w-4 border-t border-dashed border-ink-2" />
        PENDING
      </span>
      <span className="flex items-center gap-1.5">
        <span className="size-2 rounded-[2px] border border-muted" />
        Merchant
      </span>
    </div>
  )
}

function GraphStatus({ windowSec }: { windowSec: number }) {
  useEngine()
  const m = engine.metrics()
  const synced = m.streamDepth < 20
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-4 py-2.5 text-[11.5px] text-muted">
      <span>
        Nodes <b className="tabular font-medium text-ink-2">{fmtInt(m.nodes)}</b>
      </span>
      <span>
        Confirmed edges <b className="tabular font-medium text-ink-2">{fmtInt(m.edges)}</b>
      </span>
      <span>
        In flight <b className="tabular font-medium text-ink-2">{m.pending}</b>
      </span>
      <span>
        View <b className="tabular font-medium text-ink-2">{windowSec}s</b> / engine {engine.settings.windowSec}s rolling
      </span>
      <span className="ml-auto flex items-center gap-1.5">
        <span className={`size-1.5 rounded-full ${synced ? 'bg-allow' : 'bg-review'}`} />
        Redis Streams: <b className={`font-medium ${synced ? 'text-allow' : 'text-review'}`}>{synced ? 'Synced' : 'Catching up'}</b>
        <span className="tabular">· lag {formatMs(m.streamLagMs)} ms</span>
      </span>
    </div>
  )
}
