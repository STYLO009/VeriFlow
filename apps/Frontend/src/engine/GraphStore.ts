import type { TransactionEvent } from './types'

/** One confirmed edge in the live graph (mirrors `TXN|ACC|amount` in Redis sorted sets). */
export interface Edge {
  id: string
  from: string
  to: string
  amount: number
  ts: number
}

/**
 * In-memory analogue of the README's Redis adjacency indexes:
 * graph:{acc}:out / graph:{acc}:in as time-ordered lists.
 * Only SUCCESS outcomes enter this store.
 */
export class GraphStore {
  outbound = new Map<string, Edge[]>()
  inbound = new Map<string, Edge[]>()
  edges = new Map<string, Edge>()
  processed = new Set<string>()

  add(e: TransactionEvent): boolean {
    if (this.processed.has(e.transactionId)) return false
    this.processed.add(e.transactionId)
    const edge: Edge = { id: e.transactionId, from: e.senderId, to: e.receiverId, amount: e.amount, ts: e.eventTimestamp }
    this.edges.set(edge.id, edge)
    push(this.outbound, edge.from, edge)
    push(this.inbound, edge.to, edge)
    return true
  }

  /** Compensating update for a reversal: the original edge leaves the live graph. */
  remove(id: string): Edge | null {
    const edge = this.edges.get(id)
    if (!edge) return null
    this.edges.delete(id)
    pull(this.outbound, edge.from, id)
    pull(this.inbound, edge.to, id)
    return edge
  }

  /** ZRANGEBYSCORE equivalent. */
  outgoing(acc: string, from: number, to = Infinity): Edge[] {
    return range(this.outbound.get(acc), from, to)
  }
  incoming(acc: string, from: number, to = Infinity): Edge[] {
    return range(this.inbound.get(acc), from, to)
  }

  /** Drop edges older than the rolling window. Returns expired edges. */
  expire(before: number): Edge[] {
    const expired: Edge[] = []
    for (const [id, e] of this.edges) {
      if (e.ts < before) {
        expired.push(e)
        this.edges.delete(id)
      }
    }
    if (!expired.length) return expired
    for (const map of [this.outbound, this.inbound]) {
      for (const [k, list] of map) {
        const kept = list.filter((e) => e.ts >= before)
        if (kept.length) map.set(k, kept)
        else map.delete(k)
      }
    }
    return expired
  }

  degree(acc: string) {
    return (this.outbound.get(acc)?.length ?? 0) + (this.inbound.get(acc)?.length ?? 0)
  }

  clear() {
    this.outbound.clear()
    this.inbound.clear()
    this.edges.clear()
    this.processed.clear()
  }
}

function push(map: Map<string, Edge[]>, k: string, e: Edge) {
  const list = map.get(k)
  if (!list) return void map.set(k, [e])
  // Keep ordered by event time; out-of-order events are inserted in place.
  let i = list.length
  while (i > 0 && list[i - 1].ts > e.ts) i--
  list.splice(i, 0, e)
}
function pull(map: Map<string, Edge[]>, k: string, id: string) {
  const list = map.get(k)
  if (!list) return
  const next = list.filter((e) => e.id !== id)
  if (next.length) map.set(k, next)
  else map.delete(k)
}
function range(list: Edge[] | undefined, from: number, to: number) {
  if (!list) return []
  const res: Edge[] = []
  for (const e of list) if (e.ts >= from && e.ts <= to) res.push(e)
  return res
}
