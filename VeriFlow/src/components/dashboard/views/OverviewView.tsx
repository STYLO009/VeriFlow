import { CalendarDays, Pause, Play, Plus } from 'lucide-react'
import { engine } from '../../../engine/SimulationEngine'
import GraphPanel from '../GraphPanel'
import SignalsList from '../SignalsList'
import TransactionTable from '../TransactionTable'
import { useConsole, useEngine } from '../ConsoleContext'
import { Card, CardHead, EventTicker, TelemetryKpis } from '../Panels'
import { GhostButton, PageHead, PrimaryButton } from './Common'

export default function OverviewView() {
  const { running } = useEngine()
  const { inspect, go, focusGraph } = useConsole()
  const rows = engine.order.slice(0, 8).map((id) => engine.records.get(id)!).filter(Boolean)
  const signals = engine.signals.slice(0, 6)
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
