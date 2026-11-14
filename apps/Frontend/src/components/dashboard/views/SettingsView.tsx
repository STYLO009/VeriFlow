import { useState } from 'react'
import { CheckCircle2, CircleAlert, Loader2 } from 'lucide-react'
import { engine } from '../../../engine/SimulationEngine'
import { checkHealth } from '../../../engine/apiClient'
import { DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS } from '../../../engine/config'
import type { SignalKey } from '../../../engine/types'
import { formatMs } from '../../../lib/format'
import { useConsole, useEngine } from '../ConsoleContext'
import { API_BASE_URL } from '../../../lib/backendApi'
import { Card, CardHead, Segmented } from '../Panels'
import { PageHead } from './Common'

const KEYS: SignalKey[] = ['fan_out', 'fan_in', 'pass_through', 'cycle', 'multi_hop']

export default function SettingsView() {
  useEngine()
  const { theme, setTheme } = useConsole()
  const s = engine.settings
  const c = engine.connection
  const sum = KEYS.reduce((a, k) => a + s.weights[k], 0)
  const [api, setApi] = useState(c.apiBase || API_BASE_URL)
  const [ws, setWs] = useState(c.wsUrl)
  const [health, setHealth] = useState<{ state: 'idle' | 'busy' | 'ok' | 'fail'; msg?: string }>({ state: 'idle' })

  return (
    <>
      <PageHead title="Settings" sub="Scoring configuration, connections and appearance." />
      <div className="grid gap-3 xl:grid-cols-2">
        <Card>
          <CardHead
            title="Signal weights"
            sub={<span className="tabular">Σ {sum.toFixed(2)} · normalised</span>}
            right={
              <button onClick={() => engine.updateSettings({ weights: { ...DEFAULT_WEIGHTS }, thresholds: { ...DEFAULT_THRESHOLDS } })} className="text-[12px] text-muted underline underline-offset-4 hover:text-ink">
                Reset defaults
              </button>
            }
          />
          <div className="space-y-4 px-4 pb-4">
            {KEYS.map((k) => (
              <label key={k} className="grid grid-cols-[110px_1fr_44px] items-center gap-3">
                <span className="font-mono text-[12px] text-ink-2">{k}</span>
                <input
                  type="range"
                  min={0}
                  max={0.5}
                  step={0.05}
                  value={s.weights[k]}
                  onChange={(e) => engine.updateSettings({ weights: { ...s.weights, [k]: Number(e.target.value) } })}
                  className="accent-[var(--primary)]"
                />
                <span className="tabular text-right text-[12.5px] text-ink">{s.weights[k].toFixed(2)}</span>
              </label>
            ))}
          </div>
          <div className="border-t border-line px-4 py-4">
            <p className="mb-3 text-[12.5px] font-medium text-ink">Decision thresholds</p>
            <div className="grid grid-cols-3 gap-2">
              {(['monitor', 'review', 'escalate'] as const).map((k) => (
                <label key={k} className="rounded-[9px] border border-line px-3 py-2">
                  <span className="block text-[11px] uppercase tracking-wide text-muted">{k} ≥</span>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={s.thresholds[k]}
                    onChange={(e) => engine.updateSettings({ thresholds: { ...s.thresholds, [k]: Math.max(1, Math.min(100, Number(e.target.value) || 0)) } })}
                    className="tabular mt-0.5 w-full bg-transparent text-[16px] font-medium text-ink outline-none"
                  />
                </label>
              ))}
            </div>
            <p className="mt-2 text-[11.5px] text-muted">Illustrative values — calibrate on labelled data.</p>
          </div>
          <div className="flex items-center justify-between border-t border-line px-4 py-4">
            <span>
              <span className="block text-[12.5px] font-medium text-ink">Rolling window</span>
              <span className="text-[11.5px] text-muted">Engine evaluation horizon</span>
            </span>
            <Segmented
              label="Engine window"
              value={s.windowSec}
              onChange={(v) => engine.updateSettings({ windowSec: v })}
              options={[
                { value: 120, label: '120s' },
                { value: 300, label: '300s' },
                { value: 600, label: '600s' },
              ]}
            />
          </div>
        </Card>

        <div className="space-y-3">
          <Card>
            <CardHead title="Risk service" sub={c.mode === 'LOCAL' ? 'In-browser engine' : 'Node API · graph-backed evaluation'} />
            <div className="space-y-3 px-4 pb-4">
              <Segmented
                label="Evaluation mode"
                value={c.mode}
                onChange={(mode) => engine.configureConnection({ mode, apiBase: api })}
                options={[
                  { value: 'LOCAL', label: 'Local engine' },
                  { value: 'REMOTE', label: 'Remote API' },
                ]}
              />
              <div className="flex gap-2">
                <input
                  value={api}
                  onChange={(e) => setApi(e.target.value)}
                  onBlur={() => engine.configureConnection({ apiBase: api })}
                  placeholder="https://risk.example.com"
                  aria-label="API base URL"
                  className="h-9 flex-1 rounded-[9px] border border-line-strong bg-surface px-3 font-mono text-[12px] text-ink outline-none placeholder:text-faint focus:border-muted"
                />
                <button
                  disabled={!api || health.state === 'busy'}
                  onClick={async () => {
                    setHealth({ state: 'busy' })
                    engine.configureConnection({ apiBase: api })
                    const r = await checkHealth(api)
                    setHealth(r.ok ? { state: 'ok', msg: `healthy · ${formatMs(r.ms)} ms` } : { state: 'fail', msg: r.error ?? 'unreachable' })
                  }}
                  className="inline-flex h-9 items-center gap-1.5 rounded-[9px] border border-line-strong px-3 text-[12.5px] text-ink-2 hover:bg-hover disabled:opacity-40"
                >
                  {health.state === 'busy' && <Loader2 className="size-3.5 animate-spin" />}
                  GET /api/v1/health
                </button>
              </div>
              {health.state === 'ok' && (
                <p className="flex items-center gap-1.5 text-[12px] text-allow">
                  <CheckCircle2 className="size-3.5" /> {health.msg}
                </p>
              )}
              {health.state === 'fail' && (
                <p className="flex items-center gap-1.5 text-[12px] text-escalate">
                  <CircleAlert className="size-3.5" /> {health.msg}
                </p>
              )}
              {c.mode === 'REMOTE' && (
                <p className="text-[11.5px] text-muted">
                  Failures fall back to the local engine · <span className="tabular">{c.remoteFailures}</span> so far
                </p>
              )}
              <ul className="space-y-1 rounded-[10px] border border-line bg-inset p-3 font-mono text-[11px] text-ink-2">
                <li>
                  <span className="text-allow">POST</span> /api/v1/transactions/evaluate
                </li>
                <li>
                  <span className="text-allow">POST</span> /api/v1/transactions/outcome
                </li>
                <li>
                  <span className="text-monitor">GET</span> /api/v1/health
                </li>
              </ul>
            </div>
          </Card>

          <Card>
            <CardHead
              title="Event stream"
              sub="WebSocket · TransactionEvent JSON"
              right={
                <span className={`font-mono text-[11px] ${c.wsState === 'OPEN' ? 'text-allow' : c.wsState === 'ERROR' ? 'text-escalate' : 'text-muted'}`}>{c.wsState}</span>
              }
            />
            <div className="flex gap-2 px-4 pb-4">
              <input
                value={ws}
                onChange={(e) => setWs(e.target.value)}
                placeholder="wss://ingest.example.com/stream"
                aria-label="WebSocket URL"
                className="h-9 flex-1 rounded-[9px] border border-line-strong bg-surface px-3 font-mono text-[12px] text-ink outline-none placeholder:text-faint focus:border-muted"
              />
              {c.wsState === 'OPEN' || c.wsState === 'CONNECTING' ? (
                <button onClick={() => engine.disconnectWebSocket()} className="h-9 rounded-[9px] border border-line-strong px-3 text-[12.5px] text-ink-2 hover:bg-hover">
                  Disconnect
                </button>
              ) : (
                <button disabled={!ws} onClick={() => engine.connectWebSocket(ws)} className="h-9 rounded-[9px] bg-primary px-3 text-[12.5px] font-medium text-primary-fg hover:opacity-90 disabled:opacity-40">
                  Connect
                </button>
              )}
            </div>
          </Card>

          <Card>
            <div className="flex items-center justify-between px-4 py-4">
              <span>
                <span className="block text-[14.5px] font-medium text-ink">Appearance</span>
                <span className="text-[12px] text-muted">Console theme</span>
              </span>
              <Segmented
                label="Theme"
                value={theme}
                onChange={setTheme}
                options={[
                  { value: 'light', label: 'Light' },
                  { value: 'dark', label: 'Dark' },
                ]}
              />
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
