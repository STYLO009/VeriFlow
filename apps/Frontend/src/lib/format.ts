const inr = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })
const inr2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Integer paise → ₹ display. */
export function formatINR(paise: number, precise = false) {
  const r = paise / 100
  return '₹' + (precise ? inr2.format(r) : inr.format(Math.round(r)))
}

/** Compact Indian notation: ₹2.9L, ₹1.2Cr, ₹24.5K */
export function formatINRCompact(paise: number) {
  const r = paise / 100
  if (r >= 1e7) return '₹' + (r / 1e7).toFixed(1).replace(/\.0$/, '') + 'Cr'
  if (r >= 1e5) return '₹' + (r / 1e5).toFixed(1).replace(/\.0$/, '') + 'L'
  if (r >= 1e3) return '₹' + (r / 1e3).toFixed(1).replace(/\.0$/, '') + 'K'
  return '₹' + Math.round(r)
}

export function formatMs(ms: number) {
  // Browsers coarsen performance.now() to ~0.1 ms outside cross-origin isolation.
  if (ms < 0.1) return '<0.1'
  if (ms < 1) return ms.toFixed(2)
  if (ms < 10) return ms.toFixed(2)
  return ms.toFixed(1)
}

export function clock(ts: number) {
  const d = new Date(ts)
  return d.toLocaleTimeString('en-GB', { hour12: false })
}

export function ago(ts: number, now: number) {
  const s = Math.max(0, Math.round((now - ts) / 1000))
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  return `${Math.floor(m / 60)}h ago`
}

export const fmtInt = (n: number) => inr.format(n)
