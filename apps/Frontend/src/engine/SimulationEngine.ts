import { evaluateRemote, publishOutcome } from './apiClient'
import { GRAPH_CONFIG } from './config'
import { API_BASE_URL, listGraphTransactions } from '../lib/backendApi'
import { GraphStore } from './GraphStore'
import { DEFAULT_SETTINGS, evaluateCandidate, type EngineSettings } from './RiskEngine'
import { buildScenario, SCENARIOS } from './scenarios'
import type {
  Account,
  AccountRisk,
  AuditEntry,
  AuditKind,
  Decision,
  EngineMetrics,
  FraudSignal,
  GraphEvent,
  Investigation,
  InvestigationStatus,
  Pattern,
  RiskEvaluation,
  ScenarioId,
  SignalKey,
  TransactionEvent,
  TxnRecord,
  TxnStatus,
} from './types'

export type EvalMode = 'LOCAL' | 'REMOTE'
export interface ConnectionState {
  mode: EvalMode
  apiBase: string
  wsUrl: string
  wsState: 'IDLE' | 'CONNECTING' | 'OPEN' | 'CLOSED' | 'ERROR'
  remoteFailures: number
  lastError: string | null
}
export interface ActiveScenario {
  runId: number
  id: ScenarioId
  label: string
  startedAt: number
  total: number
  done: number
  accounts: string[]
}
interface StreamMsg {
  id: string
  publishedAt: number
}
interface Task {
  due: number
  run: () => void
}

const MAX_RECORDS = 3000
const pad = (n: number, w: number) => n.toString().padStart(w, '0')
const PATTERN_KEY: Record<Pattern, SignalKey> = {
  FAN_OUT: 'fan_out',
  FAN_IN: 'fan_in',
  RAPID_PASS_THROUGH: 'pass_through',
  CYCLE: 'cycle',
  MULTI_HOP: 'multi_hop',
}

function mulberry32(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export class SimulationEngine {
  readonly store = new GraphStore()
  settings: EngineSettings = structuredClone(DEFAULT_SETTINGS)
  connection: ConnectionState = { mode: 'REMOTE', apiBase: API_BASE_URL, wsUrl: '', wsState: 'IDLE', remoteFailures: 0, lastError: null }

  records = new Map<string, TxnRecord>()
  order: string[] = [] // newest first
  signals: FraudSignal[] = []
  investigations: Investigation[] = []
  audit: AuditEntry[] = []
  accounts = new Map<string, Account>()
  risk = new Map<string, AccountRisk & { at: number }>()
  scenarios: ActiveScenario[] = []

  running = false
  normalTraffic = true
  trafficRate = 2.2 // txn / sec (organic)
  started = false

  private rand = mulberry32(20261114)
  private seq = 1000
  private liveAccounts: string[] = []
  private liveMerchants = new Set<string>()
  private liveAmounts: number[] = []
  private liveAccountCursor = 0
  private runSeq = 0
  private auditSeq = 0
  private simBase = Date.now()
  private realBase = performance.now()
  private clockOverride: number | null = null
  private tasks: Task[] = []
  private stream: StreamMsg[] = []
  private nextNormalAt = 0
  private lastConsume = 0
  private lastExpire = 0
  private lastSample = 0
  private latencies: number[] = []
  private lags: number[] = []
  private evalTimes: number[] = []
  private latencyHistory: number[] = []
  private tpsHistory: number[] = []
  private decisions: Record<Decision, number> = { ALLOW: 0, MONITOR: 0, REVIEW: 0, ESCALATE: 0 }
  private evaluated = 0
  private timer: ReturnType<typeof setInterval> | null = null
  private silent = false
  private dirty = false
  private lastEmit = 0
  private version = 0
  private snapshot: { version: number; running: boolean } = { version: 0, running: false }
  private listeners = new Set<() => void>()
  private graphListeners = new Set<(e: GraphEvent) => void>()
  private ws: WebSocket | null = null

  /* ----------------------------- clock ----------------------------- */
  now(): number {
    if (this.clockOverride !== null) return this.clockOverride
    return this.running ? this.simBase + (performance.now() - this.realBase) : this.simBase
  }

  boot() {
    if (this.timer) return
    this.timer = setInterval(() => this.tick(), 50)
    if (!this.started) {
      this.started = true
      this.log('SYSTEM', 'engine', 'Graph engine online · loading backend data')
      void this.loadBackendTransactions()
      this.start()
    }
  }

  private async loadBackendTransactions() {
    try {
      // Keep the browser simulation aligned with mulegraph/data/live_demo_events.json.
      const response = await listGraphTransactions('?page=1&page_size=100')
      for (const item of response.items.slice().reverse()) {
        const senderId = item.sender?.accountRef ?? 'UNKNOWN-SENDER'
        const receiverId = item.receiver?.accountRef ?? 'UNKNOWN-RECEIVER'
        this.liveAccounts.push(senderId, receiverId)
        if (receiverId.startsWith('M')) this.liveMerchants.add(receiverId)
        this.liveAmounts.push(Number(item.amountPaise))
        this.ensureAccount(senderId)
        this.ensureAccount(receiverId)
        const event: TransactionEvent = {
          transactionId: item.transactionRef,
          senderId,
          receiverId,
          amount: Number(item.amountPaise),
          currency: item.currency ?? 'USD',
          eventTimestamp: new Date(item.eventTimestamp).getTime(),
          receivedTimestamp: new Date(item.eventTimestamp).getTime(),
          status: item.status,
          metadata: item.metadata,
        }
        const isFraud = item.metadata?.is_fraud === 1
        const evaluation: RiskEvaluation | null = isFraud
          ? {
              transactionId: event.transactionId,
              riskScore: 85,
              decision: 'ESCALATE',
              patterns: ['MULTI_HOP'],
              signals: { fan_out: 0, fan_in: 0, pass_through: 0, cycle: 0, multi_hop: 1 },
              evidence: { payment_type: item.metadata?.payment_type, is_fraud: true },
              involvedAccounts: [senderId, receiverId],
              evidenceTransactionIds: [event.transactionId],
              path: [senderId, receiverId],
              processingStatus: 'COMPLETE',
              modelVersion: 'paysim-dataset',
              evalMs: 0,
              source: 'REMOTE_API',
            }
          : null
        const record: TxnRecord = { event, evaluation, status: item.status, scenario: 'EXTERNAL', confirmedAt: item.status === 'SUCCESS' ? event.eventTimestamp : null }
        this.records.set(event.transactionId, record)
        this.order.push(event.transactionId)
        if (item.status === 'SUCCESS') this.store.add(event)
      }
      this.liveAccounts = [...new Set(this.liveAccounts)]
      this.liveAmounts = [...new Set(this.liveAmounts.filter((amount) => Number.isFinite(amount) && amount > 0))]
      const latestEvent = Math.max(...[...this.records.values()].map((record) => record.event.eventTimestamp))
      if (Number.isFinite(latestEvent)) {
        // Run the browser clock on the dataset timeline so the rolling graph
        // window does not immediately expire the historical PaySim edges.
        this.simBase = latestEvent
        this.realBase = performance.now()
        this.nextNormalAt = latestEvent
      }
      this.touch(true)
    } catch (error) {
      this.connection.lastError = error instanceof Error ? error.message : String(error)
      this.connection.remoteFailures++
      this.touch(true)
    }
  }
  destroy() {
    if (this.timer) clearInterval(this.timer)
    this.timer = null
    this.ws?.close()
  }
  start() {
    if (this.running) return
    this.realBase = performance.now()
    this.running = true
    if (this.nextNormalAt < this.now()) this.nextNormalAt = this.now()
    this.log('SYSTEM', 'clock', 'Simulation started')
    this.touch(true)
  }
  pause() {
    if (!this.running) return
    this.simBase = this.now()
    this.running = false
    this.log('SYSTEM', 'clock', 'Simulation paused')
    this.touch(true)
  }
  toggle() {
    if (this.running) this.pause()
    else this.start()
  }
  setNormalTraffic(on: boolean) {
    this.normalTraffic = on
    this.nextNormalAt = this.now()
    this.log('SYSTEM', 'traffic', on ? 'Organic UPI traffic on' : 'Organic UPI traffic off')
    this.touch(true)
  }
  setTrafficRate(r: number) {
    this.trafficRate = r
    this.touch(true)
  }

  reset() {
    this.store.clear()
    this.records.clear()
    this.order = []
    this.signals = []
    this.investigations = []
    this.risk.clear()
    this.accounts.clear()
    this.scenarios = []
    this.tasks = []
    this.stream = []
    this.latencies = []
    this.lags = []
    this.evalTimes = []
    this.latencyHistory = []
    this.tpsHistory = []
    this.decisions = { ALLOW: 0, MONITOR: 0, REVIEW: 0, ESCALATE: 0 }
    this.evaluated = 0
    this.audit = []
    this.nextNormalAt = this.now() + 600
    this.log('SYSTEM', 'graph', 'Graph reset · clean state')
    this.emitGraph({ type: 'reset' })
    this.touch(true)
  }

  /** Fast-forward so the console opens on a populated rolling window. */
  private warmup(seconds: number, scenario?: ScenarioId) {
    const end = this.now()
    let t = end - seconds * 1000
    this.nextNormalAt = t
    this.silent = true
    let fired = false
    while (t < end) {
      if (scenario && !fired && end - t < (seconds - 4) * 1000) {
        this.clockOverride = t
        this.triggerScenario(scenario)
        fired = true
      }
      this.clockOverride = t
      this.step(t)
      t += 50
    }
    this.clockOverride = null
    this.silent = false
    this.emitGraph({ type: 'reset' })
  }

  /* ----------------------------- loop ----------------------------- */
  private tick() {
    if (this.running) this.step(this.now())
    const real = performance.now()
    if (this.dirty && real - this.lastEmit > 220) {
      this.lastEmit = real
      this.dirty = false
      this.publish()
    }
  }

  private step(now: number) {
    if (this.normalTraffic) {
      let guard = 0
      while (this.nextNormalAt <= now && guard++ < 20) {
        this.generateNormal(this.nextNormalAt)
        this.nextNormalAt += (-Math.log(1 - this.rand()) / this.trafficRate) * 1000
      }
    }
    // Due tasks (settlements, scenario steps, reversals)
    if (this.tasks.length && this.tasks[0].due <= now) {
      const due: Task[] = []
      while (this.tasks.length && this.tasks[0].due <= now) due.push(this.tasks.shift()!)
      due.forEach((t) => t.run())
    }
    // Graph-update worker: XREADGROUP COUNT 10 every ~120ms
    if (now - this.lastConsume >= 120 && this.stream.length) {
      this.lastConsume = now
      this.consume(this.stream.splice(0, 10), this.now())
    }
    if (now - this.lastExpire >= 1000) {
      this.lastExpire = now
      this.expire(now)
    }
    if (now - this.lastSample >= 1000) {
      this.lastSample = now
      const m = this.computeLatency()
      this.latencyHistory.push(m.p95)
      this.tpsHistory.push(this.tps(now))
      if (this.latencyHistory.length > 48) this.latencyHistory.shift()
      if (this.tpsHistory.length > 48) this.tpsHistory.shift()
      this.dirty = true
    }
  }

  private schedule(due: number, run: () => void) {
    const t = { due, run }
    let i = this.tasks.length
    while (i > 0 && this.tasks[i - 1].due > due) i--
    this.tasks.splice(i, 0, t)
  }

  /* ------------------------- traffic ------------------------- */
  private generateNormal(ts: number) {
    if (this.liveAccounts.length < 2 || this.liveAmounts.length === 0) return
    const from = this.liveAccounts[Math.floor(this.rand() * this.liveAccounts.length)]
    let to = from
    while (to === from) to = this.liveAccounts[Math.floor(this.rand() * this.liveAccounts.length)]
    const amount = this.liveAmounts[Math.floor(this.rand() * this.liveAmounts.length)]
    this.propose(from, to, amount, 'NORMAL', ts)
  }

  triggerScenario(id: ScenarioId) {
    const meta = SCENARIOS.find((s) => s.id === id)!
    const { steps, accounts } = buildScenario(id, () => this.allocAccount(true), this.rand)
    const now = this.now()
    const run: ActiveScenario = { runId: ++this.runSeq, id, label: meta.label, startedAt: now, total: steps.length, done: 0, accounts }
    this.scenarios = [run, ...this.scenarios].slice(0, 6)
    for (const s of steps) {
      this.schedule(now + s.at, () => {
        this.propose(s.from, s.to, s.amount, id, now + s.at)
        run.done++
        this.touch()
      })
    }
    this.log('SCENARIO', meta.label, `${steps.length} synthetic transfers · ${accounts.length} accounts`)
    if (!this.running) this.start()
    this.touch(true)
    return run
  }

  private allocAccount(mule: boolean) {
    if (!this.liveAccounts.length) throw new Error('Live transaction accounts have not loaded yet')
    const id = this.liveAccounts[this.liveAccountCursor++ % this.liveAccounts.length]
    this.ensureAccount(id, mule)
    return id
  }
  private ensureAccount(id: string, young = false): Account {
    let a = this.accounts.get(id)
    if (!a) {
      a = { accountId: id, accountAgeDays: 0, createdAt: this.now(), kind: this.liveMerchants.has(id) || id.startsWith('M') ? 'MERCHANT' : 'PERSONAL', accountStatus: 'ACTIVE' }
      this.accounts.set(id, a)
    }
    return a
  }

  /* ------------------ Path 1: synchronous evaluation ------------------ */
  propose(senderId: string, receiverId: string, amount: number, scenario: TxnRecord['scenario'], ts = this.now(), id?: string) {
    // Generated proposals must remain unique across browser reloads. The
    // backend persists transactionRef and correctly rejects reusing an ID
    // with different transaction data as a 409 conflict.
    const transactionId = id ?? `TXN-${Date.now().toString(36).toUpperCase()}-${pad(++this.seq, 6)}`
    if (this.records.has(transactionId)) {
      this.log('DUPLICATE_SKIPPED', transactionId, 'Duplicate proposal ignored (idempotency)')
      return
    }
    this.ensureAccount(senderId)
    this.ensureAccount(receiverId)
    const event: TransactionEvent = {
      transactionId,
      senderId,
      receiverId,
      amount: Math.round(amount),
      currency: 'INR',
      eventTimestamp: ts,
      receivedTimestamp: this.now(),
      deviceIdHash: 'd' + ((parseInt(senderId.slice(3), 10) * 2654435761) >>> 0).toString(16).slice(0, 7),
      status: 'PENDING',
    }
    const record: TxnRecord = { event, evaluation: null, status: 'PENDING', scenario, confirmedAt: null }
    this.records.set(transactionId, record)
    this.order.unshift(transactionId)
    if (this.order.length > MAX_RECORDS) {
      for (const old of this.order.splice(MAX_RECORDS)) this.records.delete(old)
    }
    this.emitGraph({ type: 'candidate', record })

    if (this.connection.mode === 'REMOTE' && this.connection.apiBase && !this.silent) {
      evaluateRemote(this.connection.apiBase, event)
        .then((res) => this.applyEvaluation(record, res))
        .catch((err) => {
          this.connection.remoteFailures++
          this.connection.lastError = String(err?.message ?? err)
          this.log('SYSTEM', transactionId, 'Remote evaluate failed · local fallback')
          this.applyEvaluation(record, this.evaluateLocal(event))
        })
    } else {
      this.applyEvaluation(record, this.evaluateLocal(event))
    }
    if (scenario === 'EXTERNAL') return
    // Authoritative outcome from the (simulated) payment source.
    const settleIn = 450 + this.rand() * 400
    const outcome: TxnStatus = scenario === 'NORMAL' && this.rand() < 0.04 ? 'FAILED' : 'SUCCESS'
    this.schedule(ts + settleIn, () => this.settle(record, outcome))
  }

  private evaluateLocal(event: TransactionEvent): RiskEvaluation {
    const t0 = performance.now()
    const res = evaluateCandidate(event, this.store, this.settings)
    return { ...res, evalMs: performance.now() - t0, source: 'LOCAL_ENGINE' }
  }

  private applyEvaluation(record: TxnRecord, ev: RiskEvaluation) {
    record.evaluation = ev
    const now = this.now()
    this.evaluated++
    this.decisions[ev.decision]++
    this.latencies.push(ev.evalMs)
    if (this.latencies.length > 600) this.latencies.shift()
    this.evalTimes.push(now)
    if (this.evalTimes.length > 400) this.evalTimes.shift()

    // Account-level risk (kept separate from transaction risk, decays over the window)
    if (ev.decision !== 'ALLOW') {
      const core = new Set([record.event.senderId, record.event.receiverId])
      for (const acc of ev.involvedAccounts) {
        const s = core.has(acc) ? ev.riskScore : ev.riskScore * 0.8
        this.bumpRisk(acc, s, ev.patterns, now)
      }
    }
    if (ev.decision !== 'ALLOW' || record.scenario !== 'NORMAL') {
      this.log('EVALUATED', record.event.transactionId, `${ev.decision} · ${ev.riskScore.toFixed(1)} · ${ev.evalMs.toFixed(2)} ms`)
    }

    if (ev.patterns.length && ev.decision !== 'ALLOW') this.raiseSignal(record, ev, now)
    this.emitGraph({ type: 'evaluated', record })
    if (ev.decision === 'REVIEW' || ev.decision === 'ESCALATE') {
      this.emitGraph({ type: 'highlight', accounts: ev.involvedAccounts, txns: ev.evidenceTransactionIds, pattern: this.primary(ev) })
    }
    this.touch()
  }

  private primary(ev: RiskEvaluation): Pattern {
    const w = this.settings.weights
    return [...ev.patterns].sort((a, b) => w[PATTERN_KEY[b]] * ev.signals[PATTERN_KEY[b]] - w[PATTERN_KEY[a]] * ev.signals[PATTERN_KEY[a]])[0]
  }

  private bumpRisk(acc: string, score: number, patterns: Pattern[], now: number) {
    const cur = this.risk.get(acc) ?? this.blankRisk(acc)
    const decayed = this.decayedScore(cur, now)
    cur.score = Math.max(decayed, score)
    cur.at = now
    cur.patterns = Array.from(new Set([...cur.patterns, ...patterns]))
    this.risk.set(acc, cur)
  }
  private blankRisk(acc: string): AccountRisk & { at: number } {
    return { accountId: acc, score: 0, patterns: [], inCount: 0, outCount: 0, inAmount: 0, outAmount: 0, counterparties: 0, lastSeen: 0, at: 0 }
  }
  private decayedScore(r: { score: number; at: number }, now: number) {
    return r.score * Math.exp(-(now - r.at) / (this.settings.windowSec * 1000))
  }
  accountScore(acc: string) {
    const r = this.risk.get(acc)
    return r ? this.decayedScore(r, this.now()) : 0
  }

  private raiseSignal(record: TxnRecord, ev: RiskEvaluation, now: number) {
    const pattern = this.primary(ev)
    const e = ev.evidence
    const summary: Record<Pattern, string> = {
      FAN_OUT: `${e.fan_out_account} → ${e.unique_receivers_30s} receivers / 30s`,
      FAN_IN: `${e.fan_in_account} ← ${e.unique_senders_60s} senders / 60s`,
      RAPID_PASS_THROUGH: `${e.pass_through_account} forwarded ${Math.round(e.pass_through_ratio * 100)}% in ${Math.round(e.holding_time_sec ?? 0)}s`,
      CYCLE: `${e.cycle_length}-hop loop to ${record.event.receiverId}`,
      MULTI_HOP: `${e.max_path_depth}-hop chain ${ev.path[0]} → ${ev.path[ev.path.length - 1]}`,
    }
    const sig: FraudSignal = {
      id: 'SIG' + pad(this.signals.length ? parseInt(this.signals[0].id.slice(3), 10) + 1 : 1, 5),
      pattern,
      patterns: ev.patterns,
      severity: ev.decision === 'ESCALATE' ? 'HIGH' : ev.decision === 'REVIEW' ? 'MEDIUM' : 'LOW',
      riskScore: ev.riskScore,
      decision: ev.decision,
      transactionId: record.event.transactionId,
      involvedAccounts: ev.involvedAccounts,
      evidenceTransactionIds: ev.evidenceTransactionIds,
      detectedAt: now,
      summary: summary[pattern],
      scenario: record.scenario,
    }
    this.signals.unshift(sig)
    if (this.signals.length > 400) this.signals.pop()
    if (ev.decision === 'REVIEW' || ev.decision === 'ESCALATE') this.fileInvestigation(sig, now)
  }

  /** Group flagged activity into cases by shared accounts (connected evidence). */
  private fileInvestigation(sig: FraudSignal, now: number) {
    const accs = new Set(sig.involvedAccounts)
    const existing = this.investigations.find(
      (i) => i.status !== 'CLOSED' && now - i.updatedAt < this.settings.windowSec * 1000 && i.accounts.some((a) => accs.has(a)),
    )
    if (existing) {
      existing.accounts = Array.from(new Set([...existing.accounts, ...sig.involvedAccounts]))
      existing.transactionIds = Array.from(new Set([...existing.transactionIds, sig.transactionId, ...sig.evidenceTransactionIds])).slice(-120)
      if (sig.riskScore > existing.maxScore) {
        existing.maxScore = sig.riskScore
        existing.decision = sig.decision
        existing.pattern = sig.pattern
      }
      existing.updatedAt = now
      return
    }
    const id = 'CASE-' + pad(this.investigations.length + 101, 4)
    this.investigations.unshift({
      id,
      title: sig.summary,
      pattern: sig.pattern,
      status: 'OPEN',
      maxScore: sig.riskScore,
      decision: sig.decision,
      accounts: [...sig.involvedAccounts],
      transactionIds: Array.from(new Set([sig.transactionId, ...sig.evidenceTransactionIds])),
      openedAt: now,
      updatedAt: now,
    })
    this.log('CASE', id, `Opened · ${sig.pattern} · ${sig.riskScore.toFixed(1)}`)
  }
  setInvestigationStatus(id: string, status: InvestigationStatus) {
    const inv = this.investigations.find((i) => i.id === id)
    if (!inv) return
    inv.status = status
    inv.updatedAt = this.now()
    this.log('CASE', id, `Status → ${status}`)
    this.touch(true)
  }

  /* -------------- Path 2: async confirmed graph maintenance -------------- */
  private settle(record: TxnRecord, outcome: TxnStatus) {
    if (record.status !== 'PENDING') return
    record.status = outcome
    record.event = { ...record.event, status: outcome }
    // Outcome publishing is protected by a server-side source key. Only enable it
    // when explicitly provided; browser evaluation remains fully authenticated.
    if (this.connection.mode === 'REMOTE' && this.connection.apiBase && import.meta.env.VITE_OUTCOME_API_KEY) {
      publishOutcome(this.connection.apiBase, record.event).catch(() => this.connection.remoteFailures++)
    }
    if (outcome === 'SUCCESS') {
      this.stream.push({ id: record.event.transactionId, publishedAt: this.now() })
      // Occasional redelivery exercises idempotent consumption.
      if (this.rand() < 0.01) this.stream.push({ id: record.event.transactionId, publishedAt: this.now() })
      this.log('STREAM_PUBLISHED', record.event.transactionId, 'XADD transactions · SUCCESS')
      if (record.scenario === 'NORMAL' && this.rand() < 0.006) {
        this.schedule(this.now() + 4000 + this.rand() * 6000, () => this.reverse(record))
      }
    } else {
      this.log('GRAPH_DISCARDED', record.event.transactionId, 'FAILED · no confirmed edge')
      this.emitGraph({ type: 'discarded', record })
    }
    this.touch()
  }

  private consume(batch: StreamMsg[], now: number) {
    for (const msg of batch) {
      const record = this.records.get(msg.id)
      if (!record) continue
      if (!this.store.add(record.event)) {
        this.log('DUPLICATE_SKIPPED', msg.id, 'processed:' + msg.id + ' exists')
        continue
      }
      record.confirmedAt = now
      this.lags.push(now - msg.publishedAt)
      if (this.lags.length > 200) this.lags.shift()
      const { senderId: s, receiverId: r, amount } = record.event
      const sr = this.risk.get(s) ?? this.blankRisk(s)
      sr.outCount++
      sr.outAmount += amount
      sr.lastSeen = now
      this.risk.set(s, sr)
      const rr = this.risk.get(r) ?? this.blankRisk(r)
      rr.inCount++
      rr.inAmount += amount
      rr.lastSeen = now
      this.risk.set(r, rr)
      this.log('GRAPH_CONFIRMED', msg.id, `ZADD graph:${s}:out · graph:${r}:in`)
      this.emitGraph({ type: 'confirmed', record })
    }
    this.touch()
  }

  private reverse(record: TxnRecord) {
    if (record.status !== 'SUCCESS') return
    record.status = 'REVERSED'
    record.event = { ...record.event, status: 'REVERSED' }
    this.store.remove(record.event.transactionId)
    this.log('GRAPH_COMPENSATED', record.event.transactionId, 'REVERSED · compensating update applied')
    this.emitGraph({ type: 'reversed', record })
    this.touch()
  }

  private expire(now: number) {
    const expired = this.store.expire(now - this.settings.windowSec * 1000)
    if (!expired.length) return
    const touched = new Set<string>()
    expired.forEach((e) => (touched.add(e.from), touched.add(e.to)))
    const orphan = [...touched].filter((a) => this.store.degree(a) === 0)
    this.emitGraph({ type: 'expired', ids: expired.map((e) => e.id), accounts: orphan })
  }

  /* ---------------------------- external ---------------------------- */
  configureConnection(patch: Partial<ConnectionState>) {
    this.connection = { ...this.connection, ...patch }
    this.touch(true)
  }
  connectWebSocket(url: string) {
    this.ws?.close()
    this.connection.wsUrl = url
    this.connection.wsState = 'CONNECTING'
    this.touch(true)
    try {
      const ws = new WebSocket(url)
      this.ws = ws
      ws.onopen = () => {
        this.connection.wsState = 'OPEN'
        this.log('SYSTEM', 'ws', 'WebSocket connected · ' + url)
        this.touch(true)
      }
      ws.onerror = () => {
        this.connection.wsState = 'ERROR'
        this.connection.lastError = 'WebSocket error'
        this.touch(true)
      }
      ws.onclose = () => {
        if (this.connection.wsState !== 'ERROR') this.connection.wsState = 'CLOSED'
        this.touch(true)
      }
      ws.onmessage = (m) => this.ingestExternal(m.data)
    } catch (e) {
      this.connection.wsState = 'ERROR'
      this.connection.lastError = e instanceof Error ? e.message : String(e)
      this.touch(true)
    }
  }
  disconnectWebSocket() {
    this.ws?.close()
    this.ws = null
    this.connection.wsState = 'IDLE'
    this.touch(true)
  }
  /** WebSocket event interface: TransactionEvent JSON (README §5). */
  ingestExternal(raw: unknown) {
    try {
      const e = (typeof raw === 'string' ? JSON.parse(raw) : raw) as Partial<TransactionEvent>
      if (!e.transactionId || !e.senderId || !e.receiverId || !Number.isInteger(e.amount)) {
        this.log('SYSTEM', 'ws', 'Rejected malformed event')
        return
      }
      const ts = e.eventTimestamp ? (e.eventTimestamp < 1e12 ? e.eventTimestamp * 1000 : e.eventTimestamp) : this.now()
      const existing = this.records.get(e.transactionId)
      if (!existing && (!e.status || e.status === 'PENDING')) {
        this.propose(e.senderId, e.receiverId, e.amount!, 'EXTERNAL', ts, e.transactionId)
      } else if (existing && e.status && e.status !== 'PENDING') {
        if (e.status === 'REVERSED') this.reverse(existing)
        else this.settle(existing, e.status)
      }
    } catch {
      this.log('SYSTEM', 'ws', 'Unparseable event')
    }
  }

  updateSettings(patch: Partial<EngineSettings>) {
    this.settings = { ...this.settings, ...patch }
    this.log('SYSTEM', 'config', 'Scoring configuration updated')
    this.touch(true)
  }

  /* ----------------------------- metrics ----------------------------- */
  private computeLatency() {
    const sorted = [...this.latencies].sort((a, b) => a - b)
    const q = (p: number) => (sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))] : 0)
    const avg = sorted.length ? sorted.reduce((a, b) => a + b, 0) / sorted.length : 0
    return { p50: q(0.5), p95: q(0.95), p99: q(0.99), avg }
  }
  private tps(now: number) {
    const from = now - 5000
    let n = 0
    for (let i = this.evalTimes.length - 1; i >= 0 && this.evalTimes[i] >= from; i--) n++
    return n / 5
  }
  metrics(): EngineMetrics {
    const now = this.now()
    const lat = this.computeLatency()
    const open = this.investigations.filter((i) => i.status !== 'CLOSED')
    let pending = 0
    for (const id of this.order.slice(0, 80)) if (this.records.get(id)?.status === 'PENDING') pending++
    const nodes = new Set<string>()
    for (const e of this.store.edges.values()) (nodes.add(e.from), nodes.add(e.to))
    return {
      evaluated: this.evaluated,
      flagged: this.decisions.REVIEW + this.decisions.ESCALATE,
      tps: this.tps(now),
      p50: lat.p50,
      p95: lat.p95,
      p99: lat.p99,
      avgMs: lat.avg,
      streamLagMs: this.lags.length ? this.lags.slice(-20).reduce((a, b) => a + b, 0) / Math.min(20, this.lags.length) : 0,
      streamDepth: this.stream.length,
      nodes: nodes.size,
      edges: this.store.edges.size,
      pending,
      pendingReviews: open.filter((i) => i.status === 'OPEN').length,
      underInvestigation: new Set(open.flatMap((i) => i.accounts)).size,
      decisions: { ...this.decisions },
      latencyHistory: [...this.latencyHistory],
      tpsHistory: [...this.tpsHistory],
    }
  }

  /* ----------------------------- pub/sub ----------------------------- */
  private log(kind: AuditKind, ref: string, detail: string) {
    this.audit.unshift({ id: ++this.auditSeq, at: this.now(), kind, ref, detail })
    if (this.audit.length > 800) this.audit.pop()
  }
  private touch(immediate = false) {
    this.dirty = true
    if (immediate) {
      this.lastEmit = performance.now()
      this.dirty = false
      this.publish()
    }
  }
  private publish() {
    this.version++
    this.snapshot = { version: this.version, running: this.running }
    this.listeners.forEach((l) => l())
  }
  subscribe = (l: () => void) => {
    this.listeners.add(l)
    return () => void this.listeners.delete(l)
  }
  getSnapshot = () => this.snapshot
  onGraph(l: (e: GraphEvent) => void) {
    this.graphListeners.add(l)
    return () => void this.graphListeners.delete(l)
  }
  private emitGraph(e: GraphEvent) {
    if (this.silent) return
    this.graphListeners.forEach((l) => l(e))
  }

  /** Snapshot used when a graph view mounts: confirmed + in-flight edges. */
  graphState(): TxnRecord[] {
    const out: TxnRecord[] = []
    for (const id of this.order) {
      const r = this.records.get(id)
      if (!r) continue
      if (r.status === 'PENDING' || this.store.edges.has(id)) out.push(r)
      if (out.length > GRAPH_CONFIG.max_edges) break
    }
    return out
  }
  record(id: string) {
    return this.records.get(id)
  }
  /** All windowed transactions touching an account, newest first. */
  accountTxns(acc: string, limit = 200) {
    const res: TxnRecord[] = []
    for (const id of this.order) {
      const r = this.records.get(id)
      if (r && (r.event.senderId === acc || r.event.receiverId === acc)) res.push(r)
      if (res.length >= limit) break
    }
    return res
  }
}

export const engine = new SimulationEngine()
if (import.meta.hot) import.meta.hot.dispose(() => engine.destroy())
