import type { Decision, SignalKey } from './types'

/** README §9 — bounded traversal parameters. */
export const GRAPH_CONFIG = {
  time_window_seconds: 300,
  max_depth: 4,
  max_nodes: 500,
  max_edges: 1500,
}

/** README §12 — illustrative weights. */
export const DEFAULT_WEIGHTS: Record<SignalKey, number> = {
  fan_out: 0.2,
  fan_in: 0.2,
  pass_through: 0.25,
  cycle: 0.15,
  multi_hop: 0.2,
}

export const DEFAULT_THRESHOLDS = { monitor: 30, review: 60, escalate: 80 }

export const MODEL_VERSION = 'veriflow-graph-v1.0'

export function decide(score: number, t = DEFAULT_THRESHOLDS): Decision {
  if (score >= t.escalate) return 'ESCALATE'
  if (score >= t.review) return 'REVIEW'
  if (score >= t.monitor) return 'MONITOR'
  return 'ALLOW'
}

export const DECISIONS: Decision[] = ['ALLOW', 'MONITOR', 'REVIEW', 'ESCALATE']
