import { useEffect, useState } from 'react'
import { FileText, Loader2, Sparkles } from 'lucide-react'
import { generateDailyAuditReport, listBackendAudit, type BackendAudit, type DailyAuditReport } from '../../../lib/backendApi'
import { clock } from '../../../lib/format'
import { useConsole } from '../ConsoleContext'
import { Card } from '../Panels'
import { Chip, PageHead } from './Common'

export default function AuditView() {
  const { inspect } = useConsole()
  const [kind, setKind] = useState<string | null>(null)
  const [audits, setAudits] = useState<BackendAudit[]>([])
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<DailyAuditReport | null>(null)
  const [reporting, setReporting] = useState(false)
  useEffect(() => {
    let active = true
    const load = () => listBackendAudit('?page=1&pageSize=100').then((response) => active && setAudits(response.items)).catch((e) => active && setError(e instanceof Error ? e.message : 'Audit access is not permitted for this role'))
    void load()
    return () => { active = false }
  }, [])
  const kinds = [...new Set(audits.map((audit) => audit.action))]
  const rows = audits.filter((audit) => !kind || audit.action === kind)
  return (
    <>
      <PageHead title="Audit Trail" sub="State transitions across both processing paths." />
      {error && <p className="rounded-lg border border-review bg-review-bg px-3 py-2 text-[12px] text-review">{error}</p>}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5">
          <div className="flex items-center gap-2"><FileText className="size-4 text-muted" /><span><span className="block text-[13px] font-medium text-ink">Daily AI audit report</span><span className="block text-[11.5px] text-muted">Generated from today’s authenticated audit events.</span></span></div>
          <button disabled={reporting} onClick={async () => { setReporting(true); setError(null); try { setReport(await generateDailyAuditReport()) } catch (e) { setError(e instanceof Error ? e.message : 'Unable to generate report') } finally { setReporting(false) } }} className="inline-flex h-9 items-center gap-1.5 rounded-[9px] bg-primary px-3 text-[12.5px] font-medium text-primary-fg hover:opacity-90 disabled:opacity-50">{reporting ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}{reporting ? 'Generating…' : 'Generate report'}</button>
        </div>
        {report && <div className="border-t border-line bg-inset px-4 py-4"><div className="mb-2 flex flex-wrap gap-3 text-[11px] text-muted"><span>{report.date}</span><span>{report.eventCount} events analyzed</span><span>generated {new Date(report.generatedAt).toLocaleString()}</span></div><div className="whitespace-pre-wrap text-[12.5px] leading-6 text-ink-2">{report.report}</div></div>}
      </Card>
      <Card>
        <div className="flex flex-wrap gap-1.5 px-4 pb-3 pt-3.5">
          <Chip active={!kind} onClick={() => setKind(null)}>
            All
          </Chip>
          {kinds.map((k) => (
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
                  <td className="tabular border-b border-line py-2 pl-3.5 pr-3 text-muted">{clock(new Date(a.createdAt).getTime())}</td>
                  <td className="border-b border-line px-3 font-mono text-[11px] text-ink-2">{a.action}</td>
                  <td className="border-b border-line px-3">
                    {a.resourceId ? (
                      <button onClick={() => a.resource === 'Transaction' && inspect({ type: 'txn', id: a.resourceId! })} className="font-mono text-[11.5px] text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink">
                        {a.resourceId}
                      </button>
                    ) : (
                      <span className="font-mono text-[11.5px] text-ink-2">{a.resource}</span>
                    )}
                  </td>
                  <td className="border-b border-line px-3 font-mono text-[11px] text-muted">{a.actor?.email ?? a.requestId ?? 'backend audit event'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}
