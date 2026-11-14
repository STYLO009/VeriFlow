import { MODEL_VERSION, decide } from './config'
import type { Decision, Pattern, RiskEvaluation, TransactionEvent } from './types'
import { getToken } from '../lib/backendApi'

/**
 * Thin client for the README §14 contracts. Used when the console is pointed
 * at a running VeriFlow service; otherwise the in-browser engine is used.
 */
export async function evaluateRemote(base: string, txn: TransactionEvent): Promise<RiskEvaluation> {
  const t0 = performance.now()
  const root = trim(base).replace(/\/api\/v1$/, '')
  const headers = { 'Content-Type': 'application/json', ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}) }
  const res = await fetch(`${root}/api/v1/transactions/evaluate`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      transactionId: txn.transactionId,
      senderId: txn.senderId,
      receiverId: txn.receiverId,
      amountPaise: txn.amount,
      currency: txn.currency,
      eventTimestamp: new Date(txn.eventTimestamp).toISOString(),
    }),
    // Node performs a Python graph ingest followed by analysis; allow both
    // network hops to complete before falling back to the local engine.
    signal: AbortSignal.timeout(8000),
  })
  let j: any
  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    if (res.status !== 409 || error?.error?.code !== 'TRANSACTION_ALREADY_EXISTS') throw new Error(`evaluate ${res.status}`)
    const existing = await fetch(`${root}/api/v1/transactions/${encodeURIComponent(txn.transactionId)}`, {
      headers: { Authorization: headers.Authorization ?? '' },
      signal: AbortSignal.timeout(8000),
    })
    if (!existing.ok) throw new Error(`evaluate ${res.status}`)
    const stored = await existing.json()
    j = {
      riskScore: stored.risk?.riskScore ?? 0,
      decision: stored.risk?.decision ?? 'ALLOW',
      evidence: stored.risk?.evidence ?? {},
      modelVersion: stored.risk?.modelVersion ?? MODEL_VERSION,
      processingStatus: 'COMPLETE',
      patterns: [],
      alreadyExists: true,
    }
  } else {
    j = await res.json()
  }
  const evalMs = performance.now() - t0
  const score = Number(j.riskScore ?? j.risk_score ?? 0)
  const ev = j.evidence ?? {}
  return {
    transactionId: txn.transactionId,
    riskScore: score,
    decision: (j.decision as Decision) ?? decide(score),
    patterns: (j.patterns ?? []).map((p: unknown) => typeof p === 'string' ? p : (p as { name?: string }).name).filter(Boolean) as Pattern[],
    signals: { fan_out: 0, fan_in: 0, pass_through: 0, cycle: 0, multi_hop: 0, ...(j.signals ?? {}) },
    evidence: {
      unique_receivers_30s: Number(ev.uniqueReceivers ?? ev.unique_receivers_30s ?? 0),
      unique_senders_60s: Number(ev.uniqueSenders ?? ev.unique_senders_60s ?? 0),
      pass_through_ratio: Number(ev.passThroughRatio ?? ev.pass_through_ratio ?? 0),
      holding_time_sec: ev.holdingTimeSec ?? ev.holding_time_sec ?? null,
      max_path_depth: Number(ev.maxPathDepth ?? ev.max_suspicious_path_depth ?? 1),
      cycle_length: ev.cycleLength ?? null,
      fan_out_account: null,
      fan_in_account: null,
      pass_through_account: null,
    },
    involvedAccounts: j.involvedAccounts ?? [txn.senderId, txn.receiverId],
    evidenceTransactionIds: j.evidenceTransactionIds ?? [txn.transactionId],
    path: [txn.senderId, txn.receiverId],
    processingStatus: j.processingStatus ?? 'COMPLETE',
    modelVersion: j.modelVersion ?? MODEL_VERSION,
    evalMs,
    source: 'REMOTE_API',
  }
}

export async function publishOutcome(base: string, txn: TransactionEvent): Promise<void> {
  const token = getToken()
  if (!token) throw new Error('Sign in before publishing outcomes')
  const res = await fetch(`${trim(base).replace(/\/api\/v1$/, '')}/api/v1/transactions/outcome`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(import.meta.env.VITE_OUTCOME_API_KEY ? { 'x-outcome-api-key': import.meta.env.VITE_OUTCOME_API_KEY } : {}) },
    body: JSON.stringify({ transactionId: txn.transactionId, status: txn.status }),
    signal: AbortSignal.timeout(8000),
  })
  if (!res.ok) throw new Error(`outcome ${res.status}`)
}

export async function checkHealth(base: string): Promise<{ ok: boolean; ms: number; body?: unknown; error?: string }> {
  const t0 = performance.now()
  try {
    const target = trim(base).includes('/api/v1') ? trim(base) : `${trim(base)}/api/v1`
    const res = await fetch(`${target}/health`, { signal: AbortSignal.timeout(2000) })
    const body = await res.json().catch(() => null)
    return { ok: res.ok, ms: performance.now() - t0, body }
  } catch (e) {
    return { ok: false, ms: performance.now() - t0, error: e instanceof Error ? e.message : String(e) }
  }
}

const trim = (s: string) => s.replace(/\/+$/, '')
