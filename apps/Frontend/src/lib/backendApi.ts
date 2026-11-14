export type BackendUser = { id: string; email: string; role: string; isActive?: boolean }
// Use a same-origin Vite proxy in development so browser CORS policy never
// blocks the API. Production deployments can provide VITE_API_BASE_URL.
const DEFAULT_BASE = import.meta.env.DEV ? '/backend-api/api/v1' : 'http://localhost:4000/api/v1'
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || DEFAULT_BASE).replace(/\/$/, '')
const GRAPH_BASE = (import.meta.env.VITE_GRAPH_API_BASE_URL || (import.meta.env.DEV ? '/graph-api/api/v1' : 'http://localhost:8000/api/v1')).replace(/\/$/, '')
const TOKEN_KEY = 'veriflow-auth-token'; const USER_KEY = 'veriflow-auth-user'
export const getToken = () => localStorage.getItem(TOKEN_KEY)
export function getStoredUser(): BackendUser | null { try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') } catch { return null } }
export function saveSession(token: string, user: BackendUser) { localStorage.setItem(TOKEN_KEY, token); localStorage.setItem(USER_KEY, JSON.stringify(user)) }
export function clearSession() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY) }
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers); headers.set('Content-Type', 'application/json')
  const token = getToken(); if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers }); const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body?.error?.message || body?.message || `Request failed (${res.status})`)
  return body as T
}
async function graphRequest<T>(path: string): Promise<T> {
  const res = await fetch(`${GRAPH_BASE}${path}`, { headers: { Accept: 'application/json' } })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body?.error?.message || `Graph request failed (${res.status})`)
  return body as T
}
export async function login(email: string, password: string) { const result = await request<{ user: BackendUser; token: string }>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }); saveSession(result.token, result.user); return result }
export const me = () => request<{ user: BackendUser }>('/auth/me')
export const overview = () => request<{ transactions: number; accounts: number; alerts: number; settledVolumePaise: string }>('/dashboard/overview')
export const transactions = (query = '') => request<{ items: unknown[]; page: number; pageSize: number; total: number; totalPages: number }>(`/transactions${query}`)
export type BackendTransaction = { id: string; transactionRef: string; amountPaise: string | number; currency?: string; eventTimestamp: string; status: 'PENDING' | 'SUCCESS' | 'FAILED' | 'REVERSED'; sender?: { accountRef?: string }; receiver?: { accountRef?: string }; metadata?: Record<string, unknown> }
export async function listBackendTransactions(query = '?page=1&pageSize=100') { return request<{ items: BackendTransaction[]; page: number; pageSize: number; total: number; totalPages: number }>(`/transactions${query}`) }
export async function listGraphTransactions(query = '?page=1&page_size=100') { return graphRequest<{ items: BackendTransaction[]; page: number; pageSize: number; total: number; totalPages: number }>(`/transactions${query}`) }
export type BackendAccount = { id: string; accountRef: string; accountAgeDays: number | null; createdAt: string; _count?: { sentTransactions: number; receivedTransactions: number } }
export type BackendAlert = { id: string; transactionRef?: string | null; riskScore: number; decision: 'ALLOW' | 'MONITOR' | 'REVIEW' | 'ESCALATE'; modelVersion: string; evidence: unknown; createdAt: string; signals?: Array<{ patternType: string; severity: string; involvedAccountIds: unknown; evidenceTransactionIds: unknown }> }
export type BackendCase = { id: string; caseRef: string; title: string; description?: string | null; status: 'OPEN' | 'IN_REVIEW' | 'ESCALATED' | 'RESOLVED' | 'CLOSED'; priority: string; accountRefs: string[]; transactionRefs: string[]; createdAt: string; updatedAt: string }
export type BackendAudit = { id: string; action: string; resource: string; resourceId?: string | null; createdAt: string; requestId?: string | null; metadata?: unknown; actor?: { email?: string; role?: string } | null }
export const accounts = () => request<{ items: BackendAccount[]; total: number }>('/accounts')
export const alerts = () => request<{ items: BackendAlert[]; total: number }>('/alerts')
export const cases = () => request<{ items: BackendCase[]; total: number }>('/cases')
export const listBackendAccounts = (query = '?page=1&pageSize=100') => request<{ items: BackendAccount[]; total: number }>(`/accounts${query}`)
export const listBackendAlerts = (query = '?page=1&pageSize=100') => request<{ items: BackendAlert[]; total: number }>(`/alerts${query}`)
export const listBackendCases = (query = '?page=1&pageSize=100') => request<{ items: BackendCase[]; total: number }>(`/cases${query}`)
export const listBackendAudit = (query = '?page=1&pageSize=100') => request<{ items: BackendAudit[]; total: number }>(`/audit-logs${query}`)
export const updateBackendCase = (id: string, input: { status?: BackendCase['status'] }) => request<BackendCase>(`/cases/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(input) })
export type DailyAuditReport = { date: string; eventCount: number; generatedAt: string; report: string }
export const generateDailyAuditReport = (date = new Date().toISOString().slice(0, 10)) => request<DailyAuditReport>('/audit-reports/daily', { method: 'POST', body: JSON.stringify({ date }) })
export const backendTransaction = (id: string) => request<{ transaction: BackendTransaction; risk: BackendAlert | null; signals: unknown[] }>(`/transactions/${encodeURIComponent(id)}`)
export const backendAccount = (id: string) => request<BackendAccount>(`/accounts/${encodeURIComponent(id)}`)
export const backendGraph = (id: string, window = '24h') => request<Record<string, unknown>>(`/graph/${encodeURIComponent(id)}?window=${window}`)
export const backendRisk = (id: string) => request<BackendAlert & { signals: unknown[] }>(`/risk/${encodeURIComponent(id)}`)
