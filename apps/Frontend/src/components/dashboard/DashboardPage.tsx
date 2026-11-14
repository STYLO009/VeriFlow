import { useCallback, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { FileClock, FolderSearch, LayoutGrid, ListTree, Network, Settings, ShieldExclamationPoint, Sparkles, Users, ScanSearch } from 'lucide-react'
import { engine } from '../../engine/SimulationEngine'
import { navigate, type ConsoleView } from '../../lib/router'
import { stagger } from '../ui/Reveal'
import { Ctx, type ConsoleCtx, type InspectTarget } from './ConsoleContext'
import type { GraphFocus } from './CytoscapeGraph'
import Drawer from './Drawer'
import RiskInspector from './RiskInspector'
import Sidebar from './Sidebar'
import SimulationDeck from './SimulationDeck'
import Topbar from './Topbar'
import OverviewView from './views/OverviewView'
import NetworkView from './views/NetworkView'
import TransactionsView from './views/TransactionsView'
import SignalsView from './views/SignalsView'
import AccountsView from './views/AccountsView'
import InvestigationsView from './views/InvestigationsView'
import AuditView from './views/AuditView'
import SettingsView from './views/SettingsView'

const META: Record<ConsoleView, { title: string; icon: React.ReactNode; View: () => React.ReactNode }> = {
  overview: { title: 'Overview', icon: <LayoutGrid className="size-4" />, View: OverviewView },
  network: { title: 'Live Network', icon: <Network className="size-4" />, View: NetworkView },
  transactions: { title: 'Transactions', icon: <ListTree className="size-4" />, View: TransactionsView },
  signals: { title: 'Risk Signals', icon: <ShieldExclamationPoint className="size-4" />, View: SignalsView },
  accounts: { title: 'Accounts', icon: <Users className="size-4" />, View: AccountsView },
  investigations: { title: 'Investigations', icon: <FolderSearch className="size-4" />, View: InvestigationsView },
  audit: { title: 'Audit Trail', icon: <FileClock className="size-4" />, View: AuditView },
  settings: { title: 'Settings', icon: <Settings className="size-4" />, View: SettingsView },
}

export default function DashboardPage({ view }: { view: ConsoleView }) {
  const [theme, setThemeState] = useState<'light' | 'dark'>(() => (localStorage.getItem('vf-theme') as 'light' | 'dark') || 'light')
  const [inspected, setInspected] = useState<InspectTarget | null>(null)
  const [drawer, setDrawer] = useState<'inspector' | 'deck' | null>(null)
  const [focus, setFocus] = useState<GraphFocus | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [mobileNav, setMobileNav] = useState(false)

  useEffect(() => {
    engine.boot()
  }, [])

  const setTheme = useCallback((t: 'light' | 'dark') => {
    localStorage.setItem('vf-theme', t)
    setThemeState(t)
  }, [])
  const closeDrawer = useCallback(() => setDrawer(null), [])

  const ctx = useMemo<ConsoleCtx>(
    () => ({
      view,
      go: (v) => navigate(`#/console/${v}`),
      theme,
      setTheme,
      inspected,
      inspect: (t) => {
        setInspected(t)
        setDrawer(t ? 'inspector' : null)
      },
      drawer,
      openDeck: () => setDrawer('deck'),
      closeDrawer,
      focus,
      focusGraph: (accounts, txns) => setFocus({ accounts, txns, nonce: performance.now() }),
    }),
    [view, theme, setTheme, inspected, drawer, focus, closeDrawer],
  )
  const { title, icon, View } = META[view]

  return (
    <Ctx.Provider value={ctx}>
      <div data-theme={theme} className="flex h-dvh bg-bg font-sans text-ink">
        <div className="hidden h-full shrink-0 lg:block">
          <Sidebar collapsed={collapsed} onCollapse={() => setCollapsed(!collapsed)} />
        </div>
        <AnimatePresence>
          {mobileNav && (
            <>
              <motion.div className="fixed inset-0 z-40 bg-black/20 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setMobileNav(false)} />
              <motion.div className="fixed inset-y-0 left-0 z-50 lg:hidden" initial={{ x: -260 }} animate={{ x: 0 }} exit={{ x: -260 }} transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}>
                <Sidebar collapsed={false} mobile onCollapse={() => {}} onClose={() => setMobileNav(false)} />
              </motion.div>
            </>
          )}
        </AnimatePresence>

        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar title={title} icon={icon} onMenu={() => setMobileNav(true)} />
          <main className="scrollbar-thin flex-1 overflow-y-auto">
            <motion.div key={view} initial="hidden" animate="show" variants={stagger(0.07, 0.05)} className="mx-auto max-w-[1600px] space-y-3 px-4 py-6 md:px-8 md:py-7">
              <View />
            </motion.div>
          </main>
        </div>

        <Drawer
          open={drawer === 'inspector' && !!inspected}
          onClose={closeDrawer}
          title={inspected ? (inspected.type === 'txn' ? 'Risk Inspector' : 'Account Investigation') : ''}
          icon={<ScanSearch className="size-4 text-muted" />}
        >
          {inspected && <RiskInspector target={inspected} />}
        </Drawer>
        <Drawer open={drawer === 'deck'} onClose={closeDrawer} title="VeriFlow Simulator" icon={<Sparkles className="size-4 text-muted" />} width={400}>
          <SimulationDeck />
        </Drawer>
      </div>
    </Ctx.Provider>
  )
}
