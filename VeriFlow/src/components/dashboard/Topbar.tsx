import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Bell, Command, Menu, Moon, Search, FlaskConical, Sun, User, ArrowRightLeft } from 'lucide-react'
import { engine } from '../../engine/SimulationEngine'
import { ago, formatINR } from '../../lib/format'
import { DecisionBadge, PATTERN_LABEL } from '../ui/Badges'
import { EASE } from '../ui/Reveal'
import { useConsole, useEngine } from './ConsoleContext'

export default function Topbar({ title, icon, onMenu }: { title: string; icon: React.ReactNode; onMenu(): void }) {
  useEngine()
  const { openDeck, drawer, theme, setTheme } = useConsole()
  const remote = engine.connection.mode === 'REMOTE' || engine.connection.wsState === 'OPEN'
  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-4 md:px-6">
      <button onClick={onMenu} className="rounded-md p-1 text-muted lg:hidden" aria-label="Open navigation">
        <Menu className="size-4" />
      </button>
      <span className="flex items-center gap-2 text-[13.5px] text-ink-2">
        <span className="text-muted">{icon}</span>
        {title}
      </span>
      <span
        className={`ml-2 hidden items-center gap-1.5 rounded-full px-2 py-[3px] text-[10.5px] font-medium tracking-[0.04em] sm:inline-flex ${
          remote ? 'bg-allow-bg text-allow' : 'bg-review-bg text-review'
        }`}
        title={remote ? 'Connected to external service' : 'All data is synthetic'}
      >
        <span className={`size-1.5 rounded-full ${remote ? 'bg-allow' : 'bg-review'}`} />
        {remote ? 'CONNECTED' : 'SIMULATION'}
      </span>
      <div className="ml-auto flex items-center gap-2">
        <SearchBox />
        <button
          onClick={openDeck}
          className={`inline-flex h-8 items-center gap-1.5 rounded-[8px] border px-2.5 text-[12.5px] font-medium transition-colors duration-300 ${
            drawer === 'deck' ? 'border-primary bg-primary text-primary-fg' : 'border-line-strong bg-surface text-ink hover:bg-hover'
          }`}
        >
          <FlaskConical className="size-3.5" />
          <span className="max-sm:hidden">Simulate</span>
        </button>
        <button
          onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
          className="relative grid size-8 place-items-center overflow-hidden rounded-[8px] border border-line-strong bg-surface text-ink-2 transition-colors hover:bg-hover"
          aria-label={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
          title={theme === 'light' ? 'Dark mode' : 'Light mode'}
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={theme}
              initial={{ opacity: 0, rotate: -60, scale: 0.6 }}
              animate={{ opacity: 1, rotate: 0, scale: 1 }}
              exit={{ opacity: 0, rotate: 60, scale: 0.6 }}
              transition={{ duration: 0.25, ease: EASE }}
              className="grid place-items-center"
            >
              {theme === 'light' ? <Moon className="size-3.5" /> : <Sun className="size-3.5" />}
            </motion.span>
          </AnimatePresence>
        </button>
        <Notifications />
      </div>
    </header>
  )
}

function SearchBox() {
  const { inspect } = useConsole()
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        ref.current?.focus()
      }
    }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [])
  const results = useMemo(() => {
    const s = q.trim().toUpperCase()
    if (s.length < 2) return []
    const out: { type: 'account' | 'txn'; id: string; sub: string }[] = []
    for (const a of engine.accounts.values()) {
      if (a.accountId.includes(s)) out.push({ type: 'account', id: a.accountId, sub: `${a.kind.toLowerCase()} · ${engine.accountScore(a.accountId).toFixed(0)} risk` })
      if (out.length >= 4) break
    }
    for (const id of engine.order) {
      if (id.includes(s)) {
        const r = engine.records.get(id)!
        out.push({ type: 'txn', id, sub: `${r.event.senderId} → ${r.event.receiverId} · ${formatINR(r.event.amount)}` })
      }
      if (out.length >= 8) break
    }
    return out
  }, [q])
  return (
    <div className="relative max-md:hidden">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
      <input
        ref={ref}
        value={q}
        onChange={(e) => (setQ(e.target.value), setOpen(true))}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && results[0]) {
            inspect({ type: results[0].type, id: results[0].id })
            setOpen(false)
          }
        }}
        placeholder="Search account or TXN…"
        aria-label="Search accounts and transactions"
        className="h-8 w-[230px] rounded-[8px] border border-line-strong bg-surface pl-8 pr-9 text-[12.5px] text-ink outline-none transition-[border-color,width] duration-300 placeholder:text-faint focus:w-[280px] focus:border-muted"
      />
      <span className="pointer-events-none absolute right-2 top-1/2 flex -translate-y-1/2 items-center text-[10.5px] text-faint">
        <Command className="size-2.5" />K
      </span>
      <AnimatePresence>
        {open && results.length > 0 && (
          <motion.ul
            initial={{ opacity: 0, y: -4, filter: 'blur(4px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2, ease: EASE }}
            className="absolute right-0 top-10 z-50 w-[320px] overflow-hidden rounded-[10px] border border-line bg-surface p-1 shadow-pop"
          >
            {results.map((r) => (
              <li key={r.type + r.id}>
                <button
                  onMouseDown={() => inspect({ type: r.type, id: r.id })}
                  className="flex w-full items-center gap-2.5 rounded-[7px] px-2.5 py-2 text-left transition-colors hover:bg-hover"
                >
                  <span className="grid size-6 place-items-center rounded-[6px] bg-inset text-muted">
                    {r.type === 'account' ? <User className="size-3.5" /> : <ArrowRightLeft className="size-3.5" />}
                  </span>
                  <span className="min-w-0">
                    <span className="block font-mono text-[12px] text-ink">{r.id}</span>
                    <span className="block truncate text-[11px] text-muted">{r.sub}</span>
                  </span>
                </button>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  )
}

function Notifications() {
  useEngine()
  const { inspect } = useConsole()
  const [open, setOpen] = useState(false)
  const [seen, setSeen] = useState(0)
  const alerts = engine.signals.filter((s) => s.decision === 'ESCALATE' || s.decision === 'REVIEW')
  const latest = alerts[0]?.detectedAt ?? 0
  const unseen = latest > seen
  return (
    <div className="relative">
      <button
        onClick={() => (setOpen(!open), setSeen(latest))}
        className="relative grid size-8 place-items-center rounded-[8px] border border-line-strong bg-surface text-ink-2 transition-colors hover:bg-hover"
        aria-label="Notifications"
      >
        <Bell className="size-3.5" />
        {unseen && <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-escalate" />}
      </button>
      <AnimatePresence>
        {open && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <motion.div
              initial={{ opacity: 0, y: -4, filter: 'blur(4px)' }}
              animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.22, ease: EASE }}
              className="absolute right-0 top-10 z-50 w-[340px] rounded-[12px] border border-line bg-surface p-1.5 shadow-pop"
            >
              <p className="px-2.5 pb-1.5 pt-1 text-[12px] font-medium text-ink">Alerts</p>
              {alerts.slice(0, 6).map((s) => (
                <button
                  key={s.id}
                  onClick={() => (inspect({ type: 'txn', id: s.transactionId }), setOpen(false))}
                  className="flex w-full items-start gap-2.5 rounded-[8px] px-2.5 py-2 text-left transition-colors hover:bg-hover"
                >
                  <DecisionBadge decision={s.decision} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12.5px] text-ink">{PATTERN_LABEL[s.pattern]} · {s.summary}</span>
                    <span className="block text-[11px] text-muted">
                      {s.transactionId} · {ago(s.detectedAt, engine.now())}
                    </span>
                  </span>
                </button>
              ))}
              {!alerts.length && <p className="px-2.5 py-6 text-center text-[12px] text-muted">No alerts yet</p>}
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
