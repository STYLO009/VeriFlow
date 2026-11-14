import { CalendarDays, Pause, Play, Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { listBackendAlerts, listBackendTransactions, overview, type BackendAlert, type BackendTransaction } from '../../../lib/backendApi'
import { engine } from '../../../engine/SimulationEngine'
import type { FraudSignal, TxnRecord } from '../../../engine/types'
import GraphPanel from '../GraphPanel'
import SignalsList from '../SignalsList'
import TransactionTable from '../TransactionTable'
import { useConsole, useEngine } from '../ConsoleContext'
import { Card, CardHead, EventTicker, TelemetryKpis } from '../Panels'
import { GhostButton, PageHead, PrimaryButton } from './Common'

export default function OverviewView() {
  const [remote, setRemote] = useState<{ transactions: number; accounts: number; alerts: number; settledVolumePaise: string } | null>(null)
  const [remoteRows, setRemoteRows] = useState<TxnRecord[]>([])
  const [remoteSignals, setRemoteSignals] = useState<FraudSignal[]>([])
  useEffect(() => { overview().then(setRemote).catch(() => setRemote(null)) }, [])
  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const [transactionResponse, alertResponse] = await Promise.all([listBackendTransactions('?page=1&pageSize=8'), listBackendAlerts('?page=1&pageSize=6')])
        const toRecord = (item: BackendTransaction): TxnRecord => {
          const record: TxnRecord = { event: { transactionId: item.transactionRef, senderId: item.sender?.accountRef ?? 'UNKNOWN-SENDER', receiverId: item.receiver?.accountRef ?? 'UNKNOWN-RECEIVER', amount: Number(item.amountPaise), currency: item.currency ?? 'INR', eventTimestamp: new Date(item.eventTimestamp).getTime(), receivedTimestamp: new Date(item.eventTimestamp).getTime(), status: item.status, metadata: item.metadata }, evaluation: null, status: item.status, scenario: 'EXTERNAL', confirmedAt: item.status === 'SUCCESS' ? new Date(item.eventTimestamp).getTime() : null }
          engine.records.set(item.transactionRef, record)
          if (!engine.order.includes(item.transactionRef)) engine.order.push(item.transactionRef)
          return record
        }
        const toSignal = (item: BackendAlert, index: number): FraudSignal => ({ id: `${item.id}-${index}`, pattern: 'MULTI_HOP', patterns: ['MULTI_HOP'], severity: 'HIGH', riskScore: item.riskScore, decision: item.decision, transactionId: item.transactionRef ?? item.id, involvedAccounts: [], evidenceTransactionIds: item.transactionRef ? [item.transactionRef] : [], detectedAt: new Date(item.createdAt).getTime(), summary: `Backend risk alert · ${item.modelVersion}`, scenario: 'EXTERNAL' })
        if (active) { setRemoteRows(transactionResponse.items.map(toRecord)); setRemoteSignals(alertResponse.items.map(toSignal)) }
      } catch { if (active) { setRemoteRows([]); setRemoteSignals([]) } }
    }
    void load()
    const timer = window.setInterval(load, 10000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])
  const { running } = useEngine()
  const { inspect, go, focusGraph } = useConsole()
  const rows = remoteRows
  const signals = remoteSignals
  return (
    <>
      <PageHead
        title="Network Command"
        sub="Live graph risk evaluation on synthetic UPI traffic."
        right={
          <>
            <span className="inline-flex h-9 items-center gap-2 rounded-[9px] border border-line-strong bg-surface px-3 text-[13px] text-ink-2 max-sm:hidden">
              <CalendarDays className="size-3.5 text-muted" />
              {new Date(engine.now()).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}
            </span>
            <GhostButton onClick={() => engine.toggle()}>
              {running ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
              {running ? 'Pause' : 'Start'}
            </GhostButton>
            <PrimaryButton onClick={() => engine.triggerScenario('MULE_NETWORK')}>
              <Plus className="size-3.5" /> Trigger Mule Network
            </PrimaryButton>
          </>
        }
      />
      <TelemetryKpis />
      {remote && <Card><CardHead title="Backend snapshot" sub="Live data from Node API · /dashboard/overview" /><div className="grid grid-cols-2 gap-3 px-4 pb-4 md:grid-cols-4">{[['Transactions', remote.transactions], ['Accounts', remote.accounts], ['Alerts', remote.alerts], ['Settled volume (paise)', remote.settledVolumePaise]].map(([label, value]) => <div key={String(label)} className="rounded-lg border border-line bg-inset p-3"><p className="text-[11px] uppercase tracking-wide text-muted">{label}</p><p className="mt-1 font-mono text-lg text-ink">{value}</p></div>)}</div></Card>}
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
        <GraphPanel height={480} />
        <Card className="flex max-h-[600px] flex-col">
          <CardHead
            title="Risk Signals"
            right={
              <button onClick={() => go('signals')} className="text-[12.5px] text-ink-2 underline decoration-line-strong underline-offset-4 hover:text-ink">
                View All
              </button>
            }
          />
          <div className="scrollbar-thin flex-1 overflow-y-auto px-1.5 pb-2">
            <SignalsList signals={signals} onOpen={(s) => inspect({ type: 'txn', id: s.transactionId })} onTrace={(s) => focusGraph(s.involvedAccounts, s.evidenceTransactionIds)} />
          </div>
        </Card>
      </div>
      <Card>
        <CardHead
          title="Live Transactions"
          sub="Path 1 decisions as they happen"
          right={
            <button onClick={() => go('transactions')} className="text-[12.5px] text-ink-2 underline decoration-line-strong underline-offset-4 hover:text-ink">
              View All
            </button>
          }
        />
        <TransactionTable rows={rows} onOpen={(id) => inspect({ type: 'txn', id })} dense />
        <div className="pt-3">
          <EventTicker />
        </div>
      </Card>
    </>
  )
}
