import { useEffect, useState } from 'react'

export type ConsoleView = 'overview' | 'network' | 'transactions' | 'signals' | 'accounts' | 'investigations' | 'audit' | 'settings'
export type Route = { page: 'home'; anchor?: string } | { page: 'console'; view: ConsoleView }

const VIEWS: ConsoleView[] = ['overview', 'network', 'transactions', 'signals', 'accounts', 'investigations', 'audit', 'settings']

export function parse(hash: string): Route {
  const h = hash.replace(/^#\/?/, '')
  if (h.startsWith('console')) {
    const v = h.split('/')[1] as ConsoleView
    return { page: 'console', view: VIEWS.includes(v) ? v : 'overview' }
  }
  return { page: 'home', anchor: h || undefined }
}

export function navigate(to: string) {
  if (window.location.hash !== to) window.location.hash = to
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash))
  useEffect(() => {
    const on = () => setRoute(parse(window.location.hash))
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}
