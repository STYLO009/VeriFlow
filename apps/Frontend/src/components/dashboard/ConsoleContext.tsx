import { createContext, useContext, useSyncExternalStore } from 'react'
import { engine } from '../../engine/SimulationEngine'
import type { GraphFocus } from './CytoscapeGraph'
import type { ConsoleView } from '../../lib/router'

export type InspectTarget = { type: 'txn' | 'account'; id: string }

export interface ConsoleCtx {
  view: ConsoleView
  go(v: ConsoleView): void
  theme: 'light' | 'dark'
  setTheme(t: 'light' | 'dark'): void
  inspected: InspectTarget | null
  inspect(t: InspectTarget | null): void
  drawer: 'inspector' | 'deck' | null
  openDeck(): void
  closeDrawer(): void
  focus: GraphFocus | null
  focusGraph(accounts: string[], txns: string[]): void
}

export const Ctx = createContext<ConsoleCtx>(null!)
export const useConsole = () => useContext(Ctx)

/** Re-renders on throttled engine snapshots (~4 Hz). */
export function useEngine() {
  return useSyncExternalStore(engine.subscribe, engine.getSnapshot)
}
