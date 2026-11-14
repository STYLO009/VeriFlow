import { memo } from 'react'
import { motion } from 'motion/react'
import { ArrowDown, ArrowUp, ArrowRight } from 'lucide-react'
import type { TxnRecord } from '../../engine/types'
import { clock, formatINR, formatMs } from '../../lib/format'
import { DecisionBadge, ScoreText, StatusText, decisionColor } from '../ui/Badges'
import { EASE } from '../ui/Reveal'

export type SortKey = 'time' | 'amount' | 'risk' | 'eval'

interface Props {
  rows: TxnRecord[]
  onOpen(id: string): void
  sort?: { key: SortKey; dir: 'asc' | 'desc' }
  onSort?(k: SortKey): void
  dense?: boolean
  selected?: string | null
}

function TransactionTable({ rows, onOpen, sort, onSort, dense, selected }: Props) {
  const H = ({ k, children, className = '' }: { k?: SortKey; children: React.ReactNode; className?: string }) => (
    <th scope="col" className={`whitespace-nowrap px-3 py-2 text-left text-[11.5px] font-normal text-muted first:rounded-l-[8px] first:pl-3.5 last:rounded-r-[8px] ${className}`}>
      {k && onSort ? (
        <button onClick={() => onSort(k)} className="inline-flex items-center gap-1 hover:text-ink">
          {children}
          {sort?.key === k && (sort.dir === 'desc' ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />)}
        </button>
      ) : (
        children
      )}
    </th>
  )
  return (
    <div className="overflow-x-auto px-1.5 scrollbar-thin">
      <table className="w-full min-w-[860px] border-separate border-spacing-0 text-[12.5px]">
        <thead>
          <tr className="bg-inset">
            <H>TXN ID</H>
            <H>Sender → Receiver</H>
            <H k="amount" className="text-right">Amount</H>
            <H k="time">Time</H>
            <H k="eval" className="text-right">Eval</H>
            <H k="risk" className="text-right">Risk</H>
            <H>Decision</H>
            <H>State</H>
            <H className="text-right">Action</H>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const ev = r.evaluation
            const d = ev?.decision ?? 'ALLOW'
            return (
              <motion.tr
                key={r.event.transactionId}
                initial={{ opacity: 0, filter: 'blur(4px)' }}
                animate={{ opacity: 1, filter: 'blur(0px)' }}
                transition={{ duration: 0.45, ease: EASE }}
                onClick={() => onOpen(r.event.transactionId)}
                className={`group cursor-pointer transition-colors duration-150 hover:bg-hover ${selected === r.event.transactionId ? 'bg-hover' : ''}`}
              >
                <td className={`border-b border-line pl-3.5 pr-3 ${dense ? 'py-2' : 'py-2.5'}`}>
                  <span className="flex items-center gap-2.5">
                    <span className="grid size-4 shrink-0 place-items-center rounded-[4px]" style={{ background: `color-mix(in srgb, ${decisionColor(d)} 16%, transparent)` }}>
                      <span className="size-1.5 rounded-[1px]" style={{ background: decisionColor(d) }} />
                    </span>
                    <span className="font-mono text-[12px] text-ink">{r.event.transactionId}</span>
                  </span>
                </td>
                <td className="border-b border-line px-3">
                  <span className="inline-flex items-center gap-1.5 font-mono text-[11.5px] text-ink-2">
                    {r.event.senderId}
                    <ArrowRight className="size-3 text-faint" />
                    {r.event.receiverId}
                  </span>
                </td>
                <td className="tabular border-b border-line px-3 text-right text-ink">{formatINR(r.event.amount)}</td>
                <td className="tabular border-b border-line px-3 text-muted">{clock(r.event.eventTimestamp)}</td>
                <td className="tabular border-b border-line px-3 text-right text-muted">{ev ? `${formatMs(ev.evalMs)} ms` : '…'}</td>
                <td className="border-b border-line px-3 text-right">{ev ? <ScoreText score={ev.riskScore} /> : <span className="text-faint">—</span>}</td>
                <td className="border-b border-line px-3">{ev ? <DecisionBadge decision={ev.decision} /> : <span className="text-[11px] text-muted">evaluating</span>}</td>
                <td className="border-b border-line px-3">
                  <StatusText status={r.status} />
                </td>
                <td className="border-b border-line px-3 text-right">
                  <span className="text-[12px] text-muted transition-colors group-hover:text-ink">Inspect</span>
                </td>
              </motion.tr>
            )
          })}
          {!rows.length && (
            <tr>
              <td colSpan={9} className="py-12 text-center text-[12.5px] text-muted">
                No transactions match
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export default memo(TransactionTable)
