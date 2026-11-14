import { motion } from 'motion/react'
import {
  Activity,
  ChevronsUpDown,
  FileClock,
  FolderSearch,
  LayoutGrid,
  ListTree,
  Network,
  PanelLeft,
  Plus,
  Settings,
  ShieldExclamationPoint,
  Star,
  Users,
  Zap,
} from 'lucide-react'
import { engine } from '../../engine/SimulationEngine'
import type { ConsoleView } from '../../lib/router'
import { fmtInt } from '../../lib/format'
import { Logo, LogoMark } from '../brand/Logo'
import { blurIn, stagger } from '../ui/Reveal'
import { decisionColor } from '../ui/Badges'
import { useConsole, useEngine } from './ConsoleContext'

type Item = { view: ConsoleView; label: string; icon: React.ReactNode; badge?: React.ReactNode }

export default function Sidebar({ collapsed, onCollapse, mobile, onClose }: { collapsed: boolean; onCollapse(): void; mobile?: boolean; onClose?(): void }) {
  useEngine()
  const { view, go, focusGraph, openDeck } = useConsole()
  const m = engine.metrics()
  const recent = engine.signals.filter((s) => engine.now() - s.detectedAt < 60_000 && s.decision !== 'MONITOR').length
  const open = engine.investigations.filter((i) => i.status !== 'CLOSED')

  const primary: Item[] = [
    { view: 'overview', label: 'Overview', icon: <LayoutGrid className="size-4" /> },
    { view: 'network', label: 'Live Network', icon: <Network className="size-4" />, badge: <Pill tone="monitor">{m.nodes}</Pill> },
    { view: 'transactions', label: 'Transactions', icon: <ListTree className="size-4" /> },
    { view: 'signals', label: 'Risk Signals', icon: <ShieldExclamationPoint className="size-4" />, badge: recent ? <Pill tone="escalate">{recent}</Pill> : null },
    { view: 'accounts', label: 'Accounts', icon: <Users className="size-4" /> },
  ]
  const secondary: Item[] = [
    { view: 'investigations', label: 'Investigations', icon: <FolderSearch className="size-4" />, badge: open.length ? <Pill tone="allow">{open.length}</Pill> : null },
    { view: 'audit', label: 'Audit Trail', icon: <FileClock className="size-4" /> },
    { view: 'settings', label: 'Settings', icon: <Settings className="size-4" /> },
  ]
  const nav = (v: ConsoleView) => {
    go(v)
    onClose?.()
  }

  return (
    <motion.aside
      initial="hidden"
      animate="show"
      variants={stagger(0.035, 0.05)}
      className={`flex h-full flex-col border-r border-line bg-surface ${collapsed && !mobile ? 'w-[68px]' : 'w-[236px]'} transition-[width] duration-300`}
    >
      <div className={`flex h-14 shrink-0 items-center border-b border-line ${collapsed && !mobile ? 'justify-center' : 'justify-between px-4'}`}>
        {collapsed && !mobile ? (
          <button onClick={onCollapse} aria-label="Expand sidebar" className="text-ink">
            <LogoMark className="text-ink [--logo-ink:var(--surface)]" />
          </button>
        ) : (
          <>
            <a href="#/" aria-label="VeriFlow home" className="[--logo-ink:var(--surface)]">
              <Logo tone="ink" />
            </a>
            <button onClick={mobile ? onClose : onCollapse} aria-label="Collapse sidebar" className="rounded-md p-1 text-muted transition-colors hover:bg-hover hover:text-ink">
              <PanelLeft className="size-4" strokeWidth={1.6} />
            </button>
          </>
        )}
      </div>

      <div className="scrollbar-thin flex-1 overflow-y-auto px-3 pb-3">
        <Section label="Monitoring" collapsed={collapsed && !mobile} />
        {primary.map((it) => (
          <NavItem key={it.view} item={it} active={view === it.view} collapsed={collapsed && !mobile} onClick={() => nav(it.view)} />
        ))}
        <Section label="Response" collapsed={collapsed && !mobile} />
        {secondary.map((it) => (
          <NavItem key={it.view} item={it} active={view === it.view} collapsed={collapsed && !mobile} onClick={() => nav(it.view)} />
        ))}

        {!(collapsed && !mobile) && (
          <>
            <motion.div variants={blurIn} className="mt-7 flex items-center justify-between px-2.5">
              <span className="flex items-center gap-2 text-[11.5px] text-muted">
                <span className="size-3 rounded-full border border-dashed border-faint" />
                Active Cases
              </span>
              <button onClick={() => nav('investigations')} aria-label="All investigations" className="grid size-5 place-items-center rounded-full bg-inset text-muted transition-colors hover:text-ink">
                <Plus className="size-3" />
              </button>
            </motion.div>
            <div className="mt-1.5 space-y-0.5">
              {open.slice(0, 4).map((i) => (
                <motion.button
                  variants={blurIn}
                  key={i.id}
                  onClick={() => {
                    go('network')
                    focusGraph(i.accounts, i.transactionIds)
                    onClose?.()
                  }}
                  className="group flex w-full items-center gap-2.5 rounded-[8px] px-2.5 py-[6px] text-left text-[12.5px] text-ink-2 transition-colors hover:bg-hover"
                >
                  <span className="grid size-4 shrink-0 place-items-center rounded-[4px]" style={{ background: `color-mix(in srgb, ${decisionColor(i.decision)} 18%, transparent)` }}>
                    <span className="size-1.5 rounded-[1px]" style={{ background: decisionColor(i.decision) }} />
                  </span>
                  <span className="truncate">{i.title}</span>
                  <Star className="ml-auto size-3.5 shrink-0 text-faint group-hover:text-muted" />
                </motion.button>
              ))}
              {!open.length && <p className="px-2.5 py-1.5 text-[12px] text-faint">No open cases</p>}
            </div>
          </>
        )}
      </div>

      {!(collapsed && !mobile) && (
        <motion.div variants={blurIn} className="mx-3 mb-3 rounded-[10px] border border-line bg-surface p-2.5 shadow-card">
          <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-ink">
            <Zap className="size-3.5 text-muted" />
            <span className="tabular">{fmtInt(m.evaluated)}</span>
            <span className="font-normal text-muted">evaluated</span>
          </div>
          <p className="mt-0.5 text-[11.5px] text-muted">Synthetic simulation data</p>
          <button onClick={openDeck} className="mt-2 w-full rounded-[7px] bg-inset py-1.5 text-[12.5px] text-ink-2 transition-colors hover:bg-line">
            Open Simulator
          </button>
        </motion.div>
      )}
      <div className={`flex h-14 shrink-0 items-center gap-2.5 border-t border-line ${collapsed && !mobile ? 'justify-center' : 'px-4'}`}>
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-inset text-[11px] font-semibold text-ink-2">
          <Activity className="size-3.5" />
        </span>
        {!(collapsed && !mobile) && (
          <>
            <span className="min-w-0 leading-tight">
              <span className="block truncate text-[12.5px] font-medium text-ink">Risk Analyst</span>
              <span className="block truncate text-[11px] text-muted">analyst@veriflow.dev</span>
            </span>
            <ChevronsUpDown className="ml-auto size-3.5 text-muted" />
          </>
        )}
      </div>
    </motion.aside>
  )
}

function Section({ label, collapsed }: { label: string; collapsed: boolean }) {
  return (
    <motion.p variants={blurIn} className={`mb-1.5 mt-5 flex items-center gap-2 px-2.5 text-[11.5px] text-muted ${collapsed ? 'justify-center' : ''}`}>
      <span className="size-3 rounded-full border border-dashed border-faint" />
      {!collapsed && label}
    </motion.p>
  )
}

function NavItem({ item, active, collapsed, onClick }: { item: Item; active: boolean; collapsed: boolean; onClick(): void }) {
  return (
    <motion.button
      variants={blurIn}
      onClick={onClick}
      title={collapsed ? item.label : undefined}
      aria-current={active ? 'page' : undefined}
      className={`relative flex w-full items-center gap-2.5 rounded-[8px] px-2.5 py-[7px] text-[13px] transition-colors duration-200 ${
        active ? 'bg-inset font-medium text-ink' : 'text-ink-2 hover:bg-hover'
      } ${collapsed ? 'justify-center' : ''}`}
    >
      <span className={active ? 'text-ink' : 'text-muted'}>{item.icon}</span>
      {!collapsed && (
        <>
          {item.label}
          {item.badge && <span className="ml-auto">{item.badge}</span>}
        </>
      )}
    </motion.button>
  )
}

function Pill({ tone, children }: { tone: 'monitor' | 'escalate' | 'allow'; children: React.ReactNode }) {
  const cls = { monitor: 'bg-monitor-bg text-monitor', escalate: 'bg-escalate-bg text-escalate', allow: 'bg-allow-bg text-allow' }[tone]
  return <span className={`tabular rounded-full px-1.5 py-[1px] text-[10.5px] font-medium ${cls}`}>{children}</span>
}
