export type TxnStatus = 'PENDING' | 'SUCCESS' | 'FAILED' | 'REVERSED'
export type Decision = 'ALLOW' | 'MONITOR' | 'REVIEW' | 'ESCALATE'
export type Pattern = 'FAN_OUT' | 'FAN_IN' | 'RAPID_PASS_THROUGH' | 'CYCLE' | 'MULTI_HOP'
export type ScenarioId = 'FAN_OUT' | 'PASS_THROUGH' | 'CYCLE' | 'MULTI_HOP' | 'MULE_NETWORK'
export type Severity = 'LOW' | 'MEDIUM' | 'HIGH'

/** README §5 — amounts are integer paise. */
export interface TransactionEvent {
  transactionId: string
  senderId: string
  receiverId: string
  amount: number
  currency: 'INR'
  eventTimestamp: number
  receivedTimestamp: number
  deviceIdHash?: string
  status: TxnStatus
}

export interface Account {
  accountId: string
  accountAgeDays: number
  createdAt: number
  kind: 'PERSONAL' | 'MERCHANT'
  accountStatus: 'ACTIVE' | 'RESTRICTED' | 'CLOSED'
}

export interface Evidence {
  unique_receivers_30s: number
  unique_senders_60s: number
  pass_through_ratio: number
  holding_time_sec: number | null
  max_path_depth: number
  cycle_length: number | null
  fan_out_account: string | null
  fan_in_account: string | null
  pass_through_account: string | null
}

export type SignalKey = 'fan_out' | 'fan_in' | 'pass_through' | 'cycle' | 'multi_hop'

export interface RiskEvaluation {
  transactionId: string
  riskScore: number
  decision: Decision
  patterns: Pattern[]
  signals: Record<SignalKey, number>
  evidence: Evidence
  involvedAccounts: string[]
  evidenceTransactionIds: string[]
  path: string[]
  processingStatus: 'COMPLETE' | 'INCOMPLETE_EVIDENCE'
  modelVersion: string
  evalMs: number
  source: 'LOCAL_ENGINE' | 'REMOTE_API'
}

/** A transaction as tracked by the console (event + evaluation + lifecycle). */
export interface TxnRecord {
  event: TransactionEvent
  evaluation: RiskEvaluation | null
  status: TxnStatus
  scenario: ScenarioId | 'NORMAL' | 'EXTERNAL'
  confirmedAt: number | null
  reversalOf?: string
}

export interface FraudSignal {
  id: string
  pattern: Pattern
  patterns: Pattern[]
  severity: Severity
  riskScore: number
  decision: Decision
  transactionId: string
  involvedAccounts: string[]
  evidenceTransactionIds: string[]
  detectedAt: number
  summary: string
  scenario: TxnRecord['scenario']
}

export type InvestigationStatus = 'OPEN' | 'IN_REVIEW' | 'CLOSED'

export interface Investigation {
  id: string
  title: string
  pattern: Pattern
  status: InvestigationStatus
  maxScore: number
  decision: Decision
  accounts: string[]
  transactionIds: string[]
  openedAt: number
  updatedAt: number
}

export type AuditKind =
  | 'EVALUATED'
  | 'STREAM_PUBLISHED'
  | 'GRAPH_CONFIRMED'
  | 'GRAPH_DISCARDED'
  | 'GRAPH_COMPENSATED'
  | 'DUPLICATE_SKIPPED'
  | 'SCENARIO'
  | 'SYSTEM'
  | 'CASE'

export interface AuditEntry {
  id: number
  at: number
  kind: AuditKind
  ref: string
  detail: string
}

export interface EngineMetrics {
  evaluated: number
  flagged: number
  tps: number
  p50: number
  p95: number
  p99: number
  avgMs: number
  streamLagMs: number
  streamDepth: number
  nodes: number
  edges: number
  pending: number
  pendingReviews: number
  underInvestigation: number
  decisions: Record<Decision, number>
  latencyHistory: number[]
  tpsHistory: number[]
}

export type GraphEvent =
  | { type: 'candidate'; record: TxnRecord }
  | { type: 'evaluated'; record: TxnRecord }
  | { type: 'confirmed'; record: TxnRecord }
  | { type: 'discarded'; record: TxnRecord }
  | { type: 'reversed'; record: TxnRecord }
  | { type: 'expired'; ids: string[]; accounts: string[] }
  | { type: 'highlight'; accounts: string[]; txns: string[]; pattern: Pattern }
  | { type: 'reset' }

export interface AccountRisk {
  accountId: string
  score: number
  patterns: Pattern[]
  inCount: number
  outCount: number
  inAmount: number
  outAmount: number
  counterparties: number
  lastSeen: number
}
