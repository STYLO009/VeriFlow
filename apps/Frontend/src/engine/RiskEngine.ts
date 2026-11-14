import { decide, DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, GRAPH_CONFIG, MODEL_VERSION } from './config'
import type { Edge, GraphStore } from './GraphStore'
import type { Evidence, Pattern, RiskEvaluation, SignalKey, TransactionEvent } from './types'

export interface EngineSettings {
  weights: Record<SignalKey, number>
  thresholds: typeof DEFAULT_THRESHOLDS
  windowSec: number
  maxDepth: number
}

export const DEFAULT_SETTINGS: EngineSettings = {
  weights: { ...DEFAULT_WEIGHTS },
  thresholds: { ...DEFAULT_THRESHOLDS },
  windowSec: GRAPH_CONFIG.time_window_seconds,
  maxDepth: GRAPH_CONFIG.max_depth,
}

const HOP_HOLD_MS = 180_000
const FORWARD_MIN = 0.7
const clamp = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v)

/**
 * Synchronous pre-settlement evaluation (README §4.1, §17).
 * The candidate edge is evaluated against a bounded snapshot of the confirmed
 * graph and is never written to the store here.
 */
export function evaluateCandidate(
  txn: TransactionEvent,
  store: GraphStore,
  settings: EngineSettings = DEFAULT_SETTINGS,
): Omit<RiskEvaluation, 'evalMs' | 'source'> {
  const W = settings.windowSec * 1000
  const now = txn.eventTimestamp
  const since = now - W
  const cand: Edge = { id: txn.transactionId, from: txn.senderId, to: txn.receiverId, amount: txn.amount, ts: now }
  let budget = GRAPH_CONFIG.max_edges

  // Candidate graph view: confirmed snapshot + temporary candidate edge.
  const outOf = (acc: string, from = since): Edge[] => {
    const list = store.outgoing(acc, from, now)
    budget -= list.length
    return acc === cand.from ? [...list, cand] : list
  }
  const inOf = (acc: string, from = since): Edge[] => {
    const list = store.incoming(acc, from, now)
    budget -= list.length
    return acc === cand.to ? [...list, cand] : list
  }

  /* ---- Multi-hop: longest temporal chain ending in the candidate ---- */
  const forwarded = (acc: string, p: Edge) => {
    let sum = 0
    for (const o of outOf(acc, p.ts)) if (o.ts - p.ts <= HOP_HOLD_MS) sum += o.amount
    return sum
  }
  let bestChain: Edge[] = [cand]
  const visited = new Set<string>()
  const walkBack = (chain: Edge[]) => {
    if (chain.length > bestChain.length) bestChain = chain
    if (chain.length >= settings.maxDepth || budget <= 0 || visited.size > GRAPH_CONFIG.max_nodes) return
    const head = chain[0]
    const accountsInChain = new Set(chain.map((e) => e.from).concat(cand.to))
    for (const p of inOf(head.from)) {
      if (p.id === cand.id || p.ts > head.ts || head.ts - p.ts > HOP_HOLD_MS) continue
      if (now - p.ts > W || accountsInChain.has(p.from)) continue
      if (forwarded(head.from, p) < FORWARD_MIN * p.amount) continue
      const key = p.id + ':' + chain.length
      if (visited.has(key)) continue
      visited.add(key)
      walkBack([p, ...chain])
    }
  }
  walkBack([cand])
  const depth = bestChain.length
  const chainAccounts = [bestChain[0].from, ...bestChain.map((e) => e.to)]
  const multiHop = depth >= 4 ? 1 : depth === 3 ? 0.8 : depth === 2 ? 0.4 : 0

  /* ---- Cycle: bounded DFS from receiver back to sender (canonical, chronological) ---- */
  let cycle: Edge[] | null = null
  const dfs = (acc: string, path: Edge[], lastTs: number) => {
    if (cycle || budget <= 0 || path.length >= settings.maxDepth) return
    for (const e of outOf(acc)) {
      if (e.id === cand.id || e.ts < lastTs || e.ts > now) continue
      if (path.some((p) => p.from === e.to)) continue
      const next = [...path, e]
      if (e.to === cand.from) {
        cycle = [...next, cand]
        return
      }
      if (e.to === cand.to) continue
      dfs(e.to, next, e.ts)
      if (cycle) return
    }
  }
  dfs(cand.to, [], since)
  const cycleEdges: Edge[] = cycle ?? []
  let cycleSignal = 0
  if (cycleEdges.length) {
    const amts = cycleEdges.map((e) => e.amount)
    const similarity = Math.min(...amts) / Math.max(...amts)
    cycleSignal = (cycleEdges.length >= 3 ? 1 : 0.4) * (similarity >= 0.7 ? 1 : 0.5)
  }

  /* ---- Fan-out / fan-in: peak distinct counterparties in sliding windows ---- */
  const peakDistinct = (edges: Edge[], windowMs: number, key: 'to' | 'from') => {
    let best = 0
    let bestStart = 0
    for (let i = 0; i < edges.length; i++) {
      const set = new Set<string>()
      for (let j = i; j < edges.length && edges[j].ts - edges[i].ts <= windowMs; j++) set.add(edges[j][key])
      if (set.size > best) {
        best = set.size
        bestStart = edges[i].ts
      }
    }
    return { count: best, start: bestStart }
  }
  const scope = Array.from(new Set([cand.from, cand.to, ...chainAccounts]))
  let fanOut = { acc: null as string | null, n: 0, start: 0 }
  let fanIn = { acc: null as string | null, n: 0, s: 0 }
  for (const acc of scope) {
    const outs = outOf(acc)
    const fo = peakDistinct(outs, 30_000, 'to')
    if (fo.count > fanOut.n) fanOut = { acc, n: fo.count, start: fo.start }
    const ins = inOf(acc)
    const fi = peakDistinct(ins, 60_000, 'from')
    // Collectors forward what they gather; merchants retain it.
    const inAmt = ins.reduce((a, e) => a + e.amount, 0)
    const outAmt = outs.reduce((a, e) => a + e.amount, 0)
    const forwardShare = inAmt ? clamp(outAmt / inAmt / 0.7) : 0
    const s = clamp((fi.count - 2) / 6) * (0.4 + 0.6 * forwardShare)
    if (s > fanIn.s || (s === fanIn.s && fi.count > fanIn.n)) fanIn = { acc, n: fi.count, s }
  }
  const fanOutSignal = clamp((fanOut.n - 2) / 8)

  /* ---- Rapid pass-through: FIFO-matched forwarding (README §10.3) ---- */
  const passThrough = (acc: string) => {
    const ins = inOf(acc)
    const outs = outOf(acc)
    const total = ins.reduce((a, e) => a + e.amount, 0)
    if (total < 200_000 || !outs.length) return { ratio: 0, hold: null as number | null, s: 0 }
    const queue = ins.map((e) => ({ ts: e.ts, left: e.amount }))
    let matched = 0
    let holdWeighted = 0
    for (const o of outs) {
      let need = o.amount
      for (const q of queue) {
        if (need <= 0) break
        if (q.left <= 0 || q.ts > o.ts) continue
        const take = Math.min(q.left, need)
        q.left -= take
        need -= take
        matched += take
        holdWeighted += take * (o.ts - q.ts)
      }
    }
    const ratio = matched / total
    const hold = matched ? holdWeighted / matched / 1000 : null
    const speed = hold === null ? 0 : hold <= 60 ? 1 : clamp(1 - (hold - 60) / 240)
    // Mule accounts move roughly what they receive: out/in close to 1.
    const outTotal = outs.reduce((a, e) => a + e.amount, 0)
    const sym = outTotal / total
    const symmetry = sym < 0.8 ? clamp((sym - 0.5) / 0.3) : sym > 1.05 ? clamp(1 - (sym - 1.05) / 0.45) : 1
    return { ratio, hold, s: ratio < 0.5 ? 0 : clamp((ratio - 0.5) / 0.45) * speed * symmetry }
  }
  let pt = { acc: null as string | null, ratio: 0, hold: null as number | null, s: 0 }
  for (const acc of [cand.from, ...chainAccounts.slice(1, -1)]) {
    const r = passThrough(acc)
    if (r.s > pt.s || (pt.acc === null && r.ratio > pt.ratio)) pt = { acc, ...r }
  }

  /* ---- Weighted score R = Σ wᵢ·sᵢ, normalised to 0–100 ---- */
  const signals: Record<SignalKey, number> = {
    fan_out: round(fanOutSignal, 3),
    fan_in: round(fanIn.s, 3),
    pass_through: round(pt.s, 3),
    cycle: round(cycleSignal, 3),
    multi_hop: round(multiHop, 3),
  }
  const w = settings.weights
  const wSum = Object.values(w).reduce((a, b) => a + b, 0) || 1
  const raw = (Object.keys(signals) as SignalKey[]).reduce((a, k) => a + w[k] * signals[k], 0)
  const riskScore = round((raw / wSum) * 100, 1)

  const patterns: Pattern[] = []
  if (signals.fan_out >= 0.5) patterns.push('FAN_OUT')
  if (signals.fan_in >= 0.5) patterns.push('FAN_IN')
  if (signals.pass_through >= 0.5) patterns.push('RAPID_PASS_THROUGH')
  if (signals.cycle >= 0.5) patterns.push('CYCLE')
  if (signals.multi_hop >= 0.5) patterns.push('MULTI_HOP')

  const evidenceIds = new Set<string>()
  bestChain.forEach((e) => evidenceIds.add(e.id))
  cycleEdges.forEach((e) => evidenceIds.add(e.id))
  const involved = new Set<string>([cand.from, cand.to])
  if (depth > 1) chainAccounts.forEach((a) => involved.add(a))
  cycleEdges.forEach((e) => involved.add(e.from))
  if (signals.fan_out >= 0.5 && fanOut.acc) {
    involved.add(fanOut.acc)
    for (const e of outOf(fanOut.acc)) {
      if (e.ts >= fanOut.start && e.ts - fanOut.start <= 30_000 && evidenceIds.size < 40) {
        evidenceIds.add(e.id)
        involved.add(e.to)
      }
    }
  }
  if (signals.fan_in >= 0.5 && fanIn.acc) {
    involved.add(fanIn.acc)
    for (const e of inOf(fanIn.acc)) {
      if (evidenceIds.size >= 40) break
      evidenceIds.add(e.id)
      involved.add(e.from)
    }
  }

  const evidence: Evidence = {
    unique_receivers_30s: fanOut.n,
    unique_senders_60s: fanIn.n,
    pass_through_ratio: round(pt.ratio, 2),
    holding_time_sec: pt.hold === null ? null : round(pt.hold, 1),
    max_path_depth: depth,
    cycle_length: cycleEdges.length || null,
    fan_out_account: fanOut.n > 2 ? fanOut.acc : null,
    fan_in_account: fanIn.n > 2 ? fanIn.acc : null,
    pass_through_account: pt.ratio > 0 ? pt.acc : null,
  }

  return {
    transactionId: txn.transactionId,
    riskScore,
    decision: decide(riskScore, settings.thresholds),
    patterns,
    signals,
    evidence,
    involvedAccounts: Array.from(involved),
    evidenceTransactionIds: Array.from(evidenceIds),
    path: cycleEdges.length ? [...cycleEdges.map((e) => e.from), cand.from] : chainAccounts,
    processingStatus: budget <= 0 ? 'INCOMPLETE_EVIDENCE' : 'COMPLETE',
    modelVersion: MODEL_VERSION,
  }
}

function round(v: number, d: number) {
  const f = 10 ** d
  return Math.round(v * f) / f
}
