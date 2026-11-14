import { useEffect, useMemo, useState } from 'react'
import { Lock, Radio } from 'lucide-react'
import { engine } from '../../../engine/SimulationEngine'
import type { Decision, TxnRecord, TxnStatus } from '../../../engine/types'
import { DECISIONS } from '../../../engine/config'
import { listBackendTransactions, listGraphTransactions, type BackendTransaction } from '../../../lib/backendApi'
import TransactionTable, { type SortKey } from '../TransactionTable'
import { useConsole, useEngine } from '../ConsoleContext'
import { Card, Segmented } from '../Panels'
import { Chip, PageHead, Pager, SearchInput } from './Common'

const PAGE = 20

export default function TransactionsView() {
  useEngine()
  const { inspect, inspected } = useConsole()
  const [remoteRows, setRemoteRows] = useState<TxnRecord[]>([])
  const [q, setQ] = useState('')
  const [decision, setDecision] = useState<Decision | 'ALL'>('ALL')
  const [status, setStatus] = useState<TxnStatus | 'ALL'>('ALL')
  const [source, setSource] = useState<'ALL' | 'NORMAL' | 'SCENARIO'>('ALL')
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'time', dir: 'desc' })
  const [page, setPage] = useState(0)
  const [frozen, setFrozen] = useState<TxnRecord[] | null>(null)

  useEffect(() => {
    let active = true
    const toRecord = (item: BackendTransaction): TxnRecord => {
      const id = item.transactionRef
      const existing = engine.record(id)
      const event = {
        transactionId: id,
        senderId: item.sender?.accountRef ?? 'UNKNOWN-SENDER',
        receiverId: item.receiver?.accountRef ?? 'UNKNOWN-RECEIVER',
        amount: Number(item.amountPaise),
        currency: item.currency ?? 'INR',
        eventTimestamp: new Date(item.eventTimestamp).getTime(),
        receivedTimestamp: new Date(item.eventTimestamp).getTime(),
        status: item.status,
        metadata: item.metadata,
      }
      const record: TxnRecord = existing
        ? { ...existing, event: { ...existing.event, ...event }, status: item.status, scenario: 'EXTERNAL', confirmedAt: item.status === 'SUCCESS' ? event.eventTimestamp : null }
        : { event, evaluation: null, status: item.status, scenario: 'EXTERNAL', confirmedAt: item.status === 'SUCCESS' ? event.eventTimestamp : null }

      // Keep inspection actions compatible with the existing risk drawer.
      engine.records.set(id, record)
      if (!engine.order.includes(id)) engine.order.push(id)
      return record
    }
    const load = async () => {
      try {
        const response = await listBackendTransactions('?page=1&pageSize=100')
        if (active) setRemoteRows(response.items.map(toRecord))
      } catch {
        // The graph endpoint is public in local development and still contains
        // real persisted graph data when the Node API session is unavailable.
        try {
          const response = await listGraphTransactions('?page=1&page_size=100')
          if (active) setRemoteRows(response.items.map(toRecord))
        } catch {
          if (active) setRemoteRows([])
        }
      }
    }
    void load()
    const timer = window.setInterval(load, 5000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [])

  const records = frozen ?? remoteRows
  const filtered = useMemo(() => {
    const s = q.trim().toUpperCase()
    const out: TxnRecord[] = []
    for (const r of records) {
      const id = r.event.transactionId
      if (s && !id.includes(s) && !r.event.senderId.includes(s) && !r.event.receiverId.includes(s)) continue
      if (decision !== 'ALL' && r.evaluation?.decision !== decision) continue
      if (status !== 'ALL' && r.status !== status) continue
      if (source === 'NORMAL' && r.scenario !== 'NORMAL') continue
      if (source === 'SCENARIO' && r.scenario === 'NORMAL') continue
      out.push(r)
    }
    const k = sort.key
    const val = (r: (typeof out)[number]) => (k === 'amount' ? r.event.amount : k === 'risk' ? (r.evaluation?.riskScore ?? -1) : k === 'eval' ? (r.evaluation?.evalMs ?? 0) : r.event.eventTimestamp)
    out.sort((a, b) => (sort.dir === 'desc' ? val(b) - val(a) : val(a) - val(b)))
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [records, records.length, records[0]?.event.transactionId, q, decision, status, source, sort, engine.getSnapshot().version])

  const pages = Math.ceil(filtered.length / PAGE)
  const p = Math.min(page, Math.max(0, pages - 1))
  const rows = filtered.slice(p * PAGE, p * PAGE + PAGE)
  const onSort = (key: SortKey) => setSort((s) => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))

  return (
    <>
      <PageHead
        title="Transactions"
        sub="Every proposed transfer, its decision and lifecycle state."
        right={
          <Chip active={!!frozen} onClick={() => setFrozen(frozen ? null : [...remoteRows])}>
            {frozen ? <Lock className="size-3.5" /> : <Radio className="size-3.5" />}
            {frozen ? 'Frozen' : 'Live'}
          </Chip>
        }
      />
      <Card>
        <div className="flex flex-wrap items-center gap-2 px-4 pb-3 pt-3.5">
          <SearchInput value={q} onChange={(v) => (setQ(v), setPage(0))} placeholder="Search TXN or account…" />
          <div className="flex flex-wrap gap-1.5">
            {(['ALL', ...DECISIONS] as const).map((d) => (
              <Chip key={d} active={decision === d} onClick={() => (setDecision(d), setPage(0))}>
                {d === 'ALL' ? 'All decisions' : d}
              </Chip>
            ))}
          </div>
          <div className="ml-auto flex flex-wrap gap-2">
            <Segmented
              label="State"
              value={status}
              onChange={(v) => (setStatus(v), setPage(0))}
              options={[
                { value: 'ALL', label: 'All' },
                { value: 'PENDING', label: 'Pending' },
                { value: 'SUCCESS', label: 'Success' },
                { value: 'FAILED', label: 'Failed' },
                { value: 'REVERSED', label: 'Reversed' },
              ]}
            />
            <Segmented
              label="Source"
              value={source}
              onChange={(v) => (setSource(v), setPage(0))}
              options={[
                { value: 'ALL', label: 'All' },
                { value: 'NORMAL', label: 'Organic' },
                { value: 'SCENARIO', label: 'Scenario' },
              ]}
            />
          </div>
        </div>
        <TransactionTable rows={rows} onOpen={(id) => inspect({ type: 'txn', id })} sort={sort} onSort={onSort} selected={inspected?.type === 'txn' ? inspected.id : null} />
        <Pager page={p} pages={pages} total={filtered.length} onPage={setPage} />
      </Card>
    </>
  )
}
