import { useState } from 'react'
import { engine } from '../../../engine/SimulationEngine'
import type { AuditKind } from '../../../engine/types'
import { clock } from '../../../lib/format'
import { useConsole, useEngine } from '../ConsoleContext'
import { Card } from '../Panels'
import { Chip, PageHead } from './Common'

const KINDS: AuditKind[] = ['EVALUATED', 'STREAM_PUBLISHED', 'GRAPH_CONFIRMED', 'GRAPH_DISCARDED', 'GRAPH_COMPENSATED', 'DUPLICATE_SKIPPED', 'CASE', 'SCENARIO', 'SYSTEM']
const TONE: Partial<Record<AuditKind, string>> = {
  EVALUATED: 'text-monitor',
  GRAPH_CONFIRMED: 'text-allow',
  GRAPH_DISCARDED: 'text-muted',
  GRAPH_COMPENSATED: 'text-review',
  DUPLICATE_SKIPPED: 'text-review',
  CASE: 'text-escalate',
}

export default function AuditView() {
  useEngine()
  const { inspect } = useConsole()
  const [kind, setKind] = useState<AuditKind | null>(null)
  const rows = engine.audit.filter((a) => !kind || a.kind === kind).slice(0, 150)
  return (
    <>
      <PageHead title="Audit Trail" sub="State transitions across both processing paths." />
      <Card>
        <div className="flex flex-wrap gap-1.5 px-4 pb-3 pt-3.5">
          <Chip active={!kind} onClick={() => setKind(null)}>
            All
          </Chip>
          {KINDS.map((k) => (
            <Chip key={k} active={kind === k} onClick={() => setKind(k)}>
              <span className="font-mono text-[11px]">{k}</span>
            </Chip>
          ))}
        </div>
        <div className="overflow-x-auto px-1.5 pb-2 scrollbar-thin">
          <table className="w-full min-w-[720px] border-separate border-spacing-0 text-[12.5px]">
            <thead>
              <tr className="bg-inset text-left text-[11.5px] text-muted">
                {['Time', 'Event', 'Ref', 'Detail'].map((h) => (
                  <th key={h} scope="col" className="px-3 py-2 font-normal first:rounded-l-[8px] first:pl-3.5 last:rounded-r-[8px]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id} className="hover:bg-hover">
                  <td className="tabular border-b border-line py-2 pl-3.5 pr-3 text-muted">{clock(a.at)}</td>
                  <td className={`border-b border-line px-3 font-mono text-[11px] ${TONE[a.kind] ?? 'text-ink-2'}`}>{a.kind}</td>
                  <td className="border-b border-line px-3">
                    {a.ref.startsWith('TXN') && engine.record(a.ref) ? (
                      <button onClick={() => inspect({ type: 'txn', id: a.ref })} className="font-mono text-[11.5px] text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink">
                        {a.ref}
                      </button>
                    ) : (
                      <span className="font-mono text-[11.5px] text-ink-2">{a.ref}</span>
                    )}
                  </td>
                  <td className="border-b border-line px-3 font-mono text-[11px] text-muted">{a.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}
