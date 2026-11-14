import { MODEL_VERSION, decide } from './config'
import type { Decision, Pattern, RiskEvaluation, TransactionEvent } from './types'

/**
 * Thin client for the README §14 contracts. Used when the console is pointed
 * at a running VeriFlow service; otherwise the in-browser engine is used.
 */
export async function evaluateRemote(base: string, txn: TransactionEvent): Promise<RiskEvaluation> {
  const t0 = performance.now()
  const res = await fetch(`${trim(base)}/api/v1/risk/evaluate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      transactionId: txn.transactionId,
      senderId: txn.senderId,
      receiverId: txn.receiverId,
      amount: txn.amount,
      currency: txn.currency,
      eventTimestamp: Math.floor(txn.eventTimestamp / 1000),
    }),
    signal: AbortSignal.timeout(1500),
  })
  if (!res.ok) throw new Error(`evaluate ${res.status}`)
  const j = await res.json()
  const evalMs = performance.now() - t0
  const score = Number(j.riskScore ?? j.risk_score ?? 0)
  const ev = j.evidence ?? {}
  return {
    transactionId: txn.transactionId,
    riskScore: score,
    decision: (j.decision as Decision) ?? decide(score),
    patterns: (j.patterns ?? []) as Pattern[],
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
  await fetch(`${trim(base)}/api/v1/transactions/outcome`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      transactionId: txn.transactionId,
      senderId: txn.senderId,
      receiverId: txn.receiverId,
      amount: txn.amount,
      eventTimestamp: Math.floor(txn.eventTimestamp / 1000),
      status: txn.status,
    }),
    signal: AbortSignal.timeout(1500),
  })
}

export async function checkHealth(base: string): Promise<{ ok: boolean; ms: number; body?: unknown; error?: string }> {
  const t0 = performance.now()
  try {
    const res = await fetch(`${trim(base)}/health`, { signal: AbortSignal.timeout(2000) })
    const body = await res.json().catch(() => null)
    return { ok: res.ok, ms: performance.now() - t0, body }
  } catch (e) {
    return { ok: false, ms: performance.now() - t0, error: e instanceof Error ? e.message : String(e) }
  }
}

const trim = (s: string) => s.replace(/\/+$/, '')
