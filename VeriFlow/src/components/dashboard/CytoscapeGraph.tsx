import { forwardRef, memo, useEffect, useImperativeHandle, useRef } from 'react'
import cytoscape, { type Core, type ElementDefinition, type StylesheetJson } from 'cytoscape'
import cola from 'cytoscape-cola'
import { engine } from '../../engine/SimulationEngine'
import type { GraphEvent, TxnRecord } from '../../engine/types'
import { formatINR, formatINRCompact } from '../../lib/format'

cytoscape.use(cola)

export type GraphLayout = 'cola' | 'concentric' | 'breadthfirst'
export type GraphSelection = { type: 'account' | 'txn'; id: string } | null
export interface GraphFocus {
  accounts: string[]
  txns: string[]
  nonce: number
}
export interface GraphHandle {
  zoom(f: number): void
  fit(): void
  relayout(): void
  locate(acc: string): boolean
}
interface Props {
  theme: 'light' | 'dark'
  layout: GraphLayout
  windowSec: number
  hops: number
  flaggedOnly?: boolean
  focus?: GraphFocus | null
  onSelect?: (s: GraphSelection) => void
  className?: string
}

const PALETTE = {
  light: {
    node: '#c4c4c4',
    nodeBorder: '#ffffff',
    merchant: '#8f8f8f',
    label: '#7a7a7a',
    edge: '#d0d0d0',
    edgeLabel: '#5f5f5f',
    labelBg: '#ffffff',
    pending: '#6f6f6f',
    ink: '#111111',
    monitor: '#5b84e6',
    monitorFill: '#edf2fd',
    review: '#d39b1c',
    reviewFill: '#fbf0d6',
    escalate: '#d6453d',
    escalateFill: '#fde6e4',
    hl: '#d6453d',
  },
  dark: {
    node: '#4a4540',
    nodeBorder: '#141311',
    merchant: '#7a716a',
    label: '#8b847d',
    edge: '#3a3632',
    edgeLabel: '#b8b1aa',
    labelBg: '#141311',
    pending: '#efc8a9',
    ink: '#efeae4',
    monitor: '#7ea2f5',
    monitorFill: '#18213a',
    review: '#e2b04a',
    reviewFill: '#2d2412',
    escalate: '#f07067',
    escalateFill: '#341716',
    hl: '#efc8a9',
  },
}

function buildStyle(theme: 'light' | 'dark'): StylesheetJson {
  const p = PALETTE[theme]
  return [
    {
      selector: 'node',
      style: {
        width: 'mapData(score, 0, 100, 11, 34)',
        height: 'mapData(score, 0, 100, 11, 34)',
        'background-color': p.node,
        'border-width': 1.5,
        'border-color': p.nodeBorder,
        label: 'data(id)',
        'font-family': 'Inter, sans-serif',
        'font-size': 7,
        'font-weight': 500,
        color: p.label,
        'text-valign': 'bottom',
        'text-margin-y': 3,
        'min-zoomed-font-size': 7,
        'underlay-color': p.escalate,
        'underlay-opacity': 0,
        'underlay-padding': 6,
        'underlay-shape': 'ellipse',
        'transition-property': 'background-color, border-color, width, height, underlay-opacity, opacity',
        'transition-duration': 350,
      } as any,
    },
    { selector: 'node[kind = "MERCHANT"]', style: { shape: 'round-rectangle', 'background-color': p.merchant } },
    { selector: 'node[band = "monitor"]', style: { 'border-color': p.monitor, 'background-color': p.monitorFill } },
    {
      selector: 'node[band = "review"]',
      style: { 'border-color': p.review, 'background-color': p.reviewFill, 'border-width': 2, 'underlay-color': p.review, 'underlay-opacity': 0.14, color: p.review } as any,
    },
    {
      selector: 'node[band = "escalate"]',
      style: { 'border-color': p.escalate, 'background-color': p.escalate, 'border-width': 2, 'underlay-color': p.escalate, 'underlay-opacity': 0.2, 'underlay-padding': 9, color: p.escalate, 'font-size': 8 } as any,
    },
    {
      selector: 'edge',
      style: {
        width: 'data(w)',
        'curve-style': 'bezier',
        'control-point-step-size': 12,
        'line-color': p.edge,
        'target-arrow-color': p.edge,
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.65,
        label: 'data(label)',
        'font-family': 'Inter, sans-serif',
        'font-size': 6,
        color: p.edgeLabel,
        'text-background-color': p.labelBg,
        'text-background-opacity': 1,
        'text-background-padding': '1.5px',
        'text-background-shape': 'roundrectangle',
        'text-rotation': 'autorotate',
        'min-zoomed-font-size': 9,
        'transition-property': 'line-color, target-arrow-color, width, opacity',
        'transition-duration': 400,
      } as any,
    },
    { selector: 'edge[decision = "MONITOR"]', style: { 'line-color': p.monitor, 'target-arrow-color': p.monitor, opacity: 0.75 } },
    { selector: 'edge[decision = "REVIEW"]', style: { 'line-color': p.review, 'target-arrow-color': p.review, 'font-size': 7.5, 'min-zoomed-font-size': 6, color: p.review } as any },
    { selector: 'edge[decision = "ESCALATE"]', style: { 'line-color': p.escalate, 'target-arrow-color': p.escalate, 'font-size': 7.5, 'min-zoomed-font-size': 6, color: p.escalate, 'z-index': 9 } as any },
    {
      selector: 'edge.pending',
      style: { 'line-style': 'dashed', 'line-dash-pattern': [5, 4], 'line-color': p.pending, 'target-arrow-color': p.pending, opacity: 1, 'z-index': 10 } as any,
    },
    { selector: 'edge.failed', style: { 'line-style': 'dotted', opacity: 0.25 } },
    { selector: 'edge.reversed', style: { 'line-style': 'dotted', 'line-color': p.review, 'target-arrow-shape': 'tee', label: 'REVERSED', opacity: 0.7 } },
    { selector: 'edge.flash', style: { width: 6, 'line-color': p.escalate, 'target-arrow-color': p.escalate } },
    { selector: 'node.hl', style: { 'border-color': p.hl, 'border-width': 3, 'underlay-color': p.hl, 'underlay-opacity': 0.28, 'underlay-padding': 10 } as any },
    { selector: 'edge.hl', style: { 'line-color': p.hl, 'target-arrow-color': p.hl, width: 3, 'z-index': 11, 'min-zoomed-font-size': 5 } as any },
    { selector: '.dim', style: { opacity: 0.1 } },
    { selector: 'node:selected', style: { 'border-color': p.ink, 'border-width': 3, 'underlay-color': p.ink, 'underlay-opacity': 0.12, 'underlay-padding': 8, color: p.ink } as any },
    { selector: 'edge:selected', style: { 'line-color': p.ink, 'target-arrow-color': p.ink, width: 3.5, color: p.ink, 'min-zoomed-font-size': 4 } as any },
    { selector: '.out', style: { display: 'none' } },
  ]
}

const band = (s: number) => (s >= 80 ? 'escalate' : s >= 60 ? 'review' : s >= 30 ? 'monitor' : 'allow')
const weight = (paise: number) => Math.min(3.6, Math.max(0.8, Math.log10(Math.max(paise, 100) / 100) * 0.75 - 0.4))
const edgeLabel = (paise: number) => (paise >= 10_000_000 ? formatINRCompact(paise) : formatINR(paise))

function nodeDef(id: string, near?: { x: number; y: number }): ElementDefinition {
  const a = engine.accounts.get(id)
  const s = engine.accountScore(id)
  const angle = Math.random() * Math.PI * 2
  const r = 40 + Math.random() * 40
  return {
    group: 'nodes',
    data: { id, score: s, band: band(s), kind: a?.kind ?? 'PERSONAL' },
    position: near ? { x: near.x + Math.cos(angle) * r, y: near.y + Math.sin(angle) * r } : { x: (Math.random() - 0.5) * 500, y: (Math.random() - 0.5) * 360 },
  }
}
function edgeDef(r: TxnRecord): ElementDefinition {
  const e = r.event
  return {
    group: 'edges',
    data: { id: e.transactionId, source: e.senderId, target: e.receiverId, w: weight(e.amount), label: edgeLabel(e.amount), ts: e.eventTimestamp, decision: r.evaluation?.decision ?? 'PENDING' },
    classes: r.status === 'PENDING' ? 'pending' : r.status === 'REVERSED' ? 'reversed' : '',
  }
}

const CytoscapeGraph = forwardRef<GraphHandle, Props>(function CytoscapeGraph({ theme, layout, windowSec, hops, flaggedOnly, focus, onSelect, className }, ref) {
  const host = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const props = useRef({ layout, windowSec, hops, flaggedOnly, onSelect })
  props.current = { layout, windowSec, hops, flaggedOnly, onSelect }
  const layoutRef = useRef<cytoscape.Layouts | null>(null)
  const relayoutRef = useRef<(fit?: boolean) => void>(() => {})
  const windowRef = useRef<() => void>(() => {})
  const autoFitRef = useRef<() => void>(() => {})
  const holdRef = useRef<() => void>(() => {})

  useImperativeHandle(ref, () => ({
    zoom(f) {
      const cy = cyRef.current
      if (!cy) return
      cy.animate({ zoom: { level: cy.zoom() * f, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } } } as any, { duration: 220, easing: 'ease-out-cubic' })
    },
    fit() {
      autoFitRef.current()
      cyRef.current?.animate({ fit: { eles: cyRef.current.elements(':visible'), padding: 36 } } as any, { duration: 380, easing: 'ease-out-cubic' })
    },
    relayout() {
      relayoutRef.current(true)
    },
    locate(acc) {
      const cy = cyRef.current
      const n = cy?.getElementById(acc)
      if (!cy || !n || n.empty()) return false
      holdRef.current()
      cy.elements().unselect()
      n.select()
      highlightNeighborhood(cy, n, props.current.hops)
      cy.animate({ center: { eles: n }, zoom: Math.max(cy.zoom(), 1.3) } as any, { duration: 420, easing: 'ease-out-cubic' })
      props.current.onSelect?.({ type: 'account', id: acc })
      return true
    },
  }))

  useEffect(() => {
    const cy = cytoscape({
      container: host.current!,
      style: buildStyle(theme),
      minZoom: 0.15,
      maxZoom: 4,
      boxSelectionEnabled: false,
      selectionType: 'single',
      pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
      textureOnViewport: false,
      hideEdgesOnViewport: false,
    })
    cyRef.current = cy
    if (import.meta.env.DEV) (window as any).__cy = cy
    const timers = new Set<ReturnType<typeof setTimeout>>()
    const later = (ms: number, fn: () => void) => {
      const t = setTimeout(() => (timers.delete(t), fn()), ms)
      timers.add(t)
    }

    /* ---------- layout (incremental, throttled) ---------- */
    let lastLayout = 0
    let newNodes = false
    // Auto-frame the graph until the analyst takes control of the viewport.
    let userMoved = false
    autoFitRef.current = () => (userMoved = false)
    holdRef.current = () => (userMoved = true)
    host.current!.addEventListener('wheel', () => (userMoved = true), { passive: true })
    cy.on('dragpan', () => (userMoved = true))
    cy.on('pinchzoom', () => (userMoved = true))
    const runLayout = (fit = false, initial = false) => {
      layoutRef.current?.stop()
      const eles = cy.elements(':visible')
      const mode = props.current.layout
      const opts: any =
        mode === 'cola'
          ? { name: 'cola', animate: true, randomize: initial, fit, padding: 56, maxSimulationTime: initial ? 2600 : 1400, nodeSpacing: 8, edgeLength: 66, avoidOverlap: true, handleDisconnected: true, convergenceThreshold: 0.02 }
          : mode === 'concentric'
            ? { name: 'concentric', animate: true, animationDuration: 600, fit, padding: 36, concentric: (n: any) => n.data('score') + n.degree() * 2, levelWidth: () => 12, minNodeSpacing: 10 }
            : { name: 'breadthfirst', directed: true, animate: true, animationDuration: 600, fit, padding: 36, spacingFactor: 0.9, roots: rootsFor(cy) }
      layoutRef.current = eles.layout(opts)
      layoutRef.current.one('layoutstop', () => {
        if (!userMoved && !cy.destroyed()) cy.animate({ fit: { eles: cy.elements(':visible'), padding: 56 } } as any, { duration: 450, easing: 'ease-out-cubic' })
      })
      layoutRef.current.run()
      lastLayout = performance.now()
      newNodes = false
    }
    relayoutRef.current = (fit = false) => runLayout(fit)

    /* ---------- time window & flagged filter ---------- */
    const applyWindow = () => {
      const cutoff = engine.now() - props.current.windowSec * 1000
      const flagged = props.current.flaggedOnly
      cy.batch(() => {
        cy.edges().forEach((e) => {
          const old = !e.hasClass('pending') && e.data('ts') < cutoff
          const filtered = flagged && (e.data('decision') === 'ALLOW' || e.data('decision') === 'PENDING')
          e.toggleClass('out', old || !!filtered)
        })
        cy.nodes().forEach((n) => {
          const visible = n.connectedEdges().some((e: any) => !e.hasClass('out'))
          n.toggleClass('out', !visible && !n.selected())
        })
      })
    }
    windowRef.current = applyWindow

    /* ---------- initial snapshot ---------- */
    const load = () => {
      cy.elements().remove()
      const recs = engine.graphState()
      const nodes = new Set<string>()
      const defs: ElementDefinition[] = []
      for (const r of recs) {
        for (const a of [r.event.senderId, r.event.receiverId]) {
          if (!nodes.has(a)) {
            nodes.add(a)
            defs.push(nodeDef(a))
          }
        }
      }
      for (const r of recs) defs.push(edgeDef(r))
      cy.batch(() => cy.add(defs))
      applyWindow()
      runLayout(true, true)
    }
    load()

    /* ---------- live events, flushed once per frame ---------- */
    let queue: GraphEvent[] = []
    let raf = 0
    const ensureNode = (id: string, near?: string) => {
      if (cy.getElementById(id).nonempty()) return
      const n = near ? cy.getElementById(near) : null
      cy.add(nodeDef(id, n && n.nonempty() ? n.position() : undefined))
      newNodes = true
    }
    const refreshNode = (id: string) => {
      const n = cy.getElementById(id)
      if (n.empty()) return
      const s = engine.accountScore(id)
      n.data({ score: s, band: band(s) })
    }
    const flush = () => {
      raf = 0
      const batch = queue
      queue = []
      let reset = false
      cy.batch(() => {
        for (const ev of batch) {
          switch (ev.type) {
            case 'reset':
              reset = true
              break
            case 'candidate': {
              const { senderId: s, receiverId: r } = ev.record.event
              const sExists = cy.getElementById(s).nonempty()
              ensureNode(s, r)
              ensureNode(r, sExists ? s : undefined)
              if (cy.getElementById(ev.record.event.transactionId).empty()) cy.add(edgeDef(ev.record))
              break
            }
            case 'evaluated': {
              const ev2 = ev.record.evaluation!
              const e = cy.getElementById(ev.record.event.transactionId)
              e.data('decision', ev2.decision)
              if (ev2.decision !== 'ALLOW') ev2.involvedAccounts.forEach(refreshNode)
              if (ev2.decision === 'ESCALATE') {
                e.addClass('flash')
                later(650, () => e.removeClass('flash'))
              }
              break
            }
            case 'confirmed': {
              const e = cy.getElementById(ev.record.event.transactionId)
              e.removeClass('pending')
              e.removeStyle('line-dash-offset')
              break
            }
            case 'discarded': {
              const e = cy.getElementById(ev.record.event.transactionId)
              e.removeClass('pending').addClass('failed')
              later(1400, () => {
                const ends = e.connectedNodes()
                e.remove()
                ends.forEach((n) => void (n.degree(false) === 0 && n.remove()))
              })
              break
            }
            case 'reversed':
              cy.getElementById(ev.record.event.transactionId).removeClass('pending').addClass('reversed')
              break
            case 'expired': {
              for (const id of ev.ids) cy.getElementById(id).remove()
              for (const a of ev.accounts) {
                const n = cy.getElementById(a)
                if (n.nonempty() && n.degree(false) === 0) n.remove()
              }
              break
            }
            case 'highlight': {
              const els = cy.collection()
              ev.accounts.forEach((a) => (els.merge(cy.getElementById(a)) as unknown))
              ev.txns.forEach((t) => (els.merge(cy.getElementById(t)) as unknown))
              els.addClass('hl')
              later(9000, () => els.removeClass('hl'))
              break
            }
          }
        }
      })
      if (reset) return load()
      applyWindow()
      if (newNodes && performance.now() - lastLayout > 2200 && !cy.elements(':selected').length) runLayout(false)
    }
    const off = engine.onGraph((e) => {
      queue.push(e)
      if (!raf) raf = requestAnimationFrame(flush)
    })

    /* ---------- pending dash animation (only in-flight edges) ---------- */
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let offset = 0
    let dashRaf = 0
    let lastDash = 0
    const dash = (t: number) => {
      dashRaf = requestAnimationFrame(dash)
      if (t - lastDash < 33) return
      lastDash = t
      const pend = cy.edges('.pending')
      if (!pend.length) return
      offset = (offset + 1.2) % 90
      pend.style('line-dash-offset', -offset)
    }
    if (!reduce) dashRaf = requestAnimationFrame(dash)

    /* ---------- periodic window / risk decay ---------- */
    const iv = setInterval(() => {
      cy.batch(() => cy.nodes().forEach((n) => refreshNode(n.id())))
      applyWindow()
    }, 1500)

    /* ---------- interaction ---------- */
    cy.on('tap', 'node', (e) => {
      highlightNeighborhood(cy, e.target, props.current.hops)
      props.current.onSelect?.({ type: 'account', id: e.target.id() })
    })
    cy.on('tap', 'edge', (e) => {
      clearDim(cy)
      const edge = e.target
      cy.elements().addClass('dim')
      edge.union(edge.connectedNodes()).removeClass('dim')
      props.current.onSelect?.({ type: 'txn', id: edge.id() })
    })
    cy.on('tap', (e) => {
      if (e.target === cy) {
        clearDim(cy)
        props.current.onSelect?.(null)
      }
    })
    cy.on('mouseover', 'node, edge', () => host.current && (host.current.style.cursor = 'pointer'))
    cy.on('mouseout', 'node, edge', () => host.current && (host.current.style.cursor = 'default'))

    const ro = new ResizeObserver(() => cy.resize())
    ro.observe(host.current!)

    return () => {
      off()
      ro.disconnect()
      cancelAnimationFrame(raf)
      cancelAnimationFrame(dashRaf)
      clearInterval(iv)
      timers.forEach(clearTimeout)
      layoutRef.current?.stop()
      cy.destroy()
      cyRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    cyRef.current?.style(buildStyle(theme))
  }, [theme])
  useEffect(() => {
    if (cyRef.current) relayoutRef.current(true)
  }, [layout])
  useEffect(() => {
    windowRef.current()
  }, [windowSec, flaggedOnly])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !focus) return
    clearDim(cy)
    const els = cy.collection()
    focus.accounts.forEach((a) => els.merge(cy.getElementById(a)))
    focus.txns.forEach((t) => els.merge(cy.getElementById(t)))
    if (els.empty()) return
    holdRef.current()
    cy.elements().addClass('dim')
    els.removeClass('dim').addClass('hl')
    els.edgesWith(els).removeClass('dim')
    cy.animate({ fit: { eles: els, padding: 70 } } as any, { duration: 480, easing: 'ease-out-cubic' })
    const t = setTimeout(() => els.removeClass('hl'), 9000)
    return () => clearTimeout(t)
  }, [focus?.nonce])

  return (
    <div className={className}>
      <div ref={host} className="h-full w-full" role="application" aria-label="Live transaction network graph" />
    </div>
  )
})

function clearDim(cy: Core) {
  cy.elements('.dim').removeClass('dim')
}

function highlightNeighborhood(cy: Core, node: cytoscape.NodeSingular, hops: number) {
  clearDim(cy)
  let hood = node.closedNeighborhood()
  for (let i = 1; i < hops; i++) hood = hood.union(hood.nodes().closedNeighborhood())
  cy.elements().addClass('dim')
  hood.removeClass('dim')
}

function rootsFor(cy: Core) {
  const roots = cy.nodes(':visible').filter((n) => n.indegree(false) === 0 && n.outdegree(false) > 0)
  return roots.length ? roots : undefined
}

export default memo(CytoscapeGraph)
