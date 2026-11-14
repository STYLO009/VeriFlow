import type { ScenarioId } from './types'

export interface ScenarioStep {
  at: number // ms after trigger
  from: string
  to: string
  amount: number // paise
}

export interface ScenarioMeta {
  id: ScenarioId
  label: string
  short: string
  pattern: string
}

export const SCENARIOS: ScenarioMeta[] = [
  { id: 'MULE_NETWORK', label: 'Mule Network', short: 'Split · layer · consolidate', pattern: 'Coordinated' },
  { id: 'FAN_OUT', label: 'Fan-Out Burst', short: '1 → 12 mules in < 30s', pattern: 'FAN_OUT' },
  { id: 'PASS_THROUGH', label: 'Mule Pass-Through', short: 'A → B → C at ~96%', pattern: 'RAPID_PASS_THROUGH' },
  { id: 'CYCLE', label: 'Circular Ring', short: 'A → B → C → D → A', pattern: 'CYCLE' },
  { id: 'MULTI_HOP', label: 'Multi-Hop Layering', short: '4-hop laundering chain', pattern: 'MULTI_HOP' },
]

type Alloc = () => string
type Rand = () => number

const rupees = (r: number) => Math.round(r * 100)
const jitter = (rand: Rand, base: number, pct: number) => Math.round(base * (1 + (rand() * 2 - 1) * pct))

/** Deterministic attack playbooks. Amounts are integer paise. */
export function buildScenario(id: ScenarioId, alloc: Alloc, rand: Rand): { steps: ScenarioStep[]; accounts: string[] } {
  const steps: ScenarioStep[] = []
  const accounts: string[] = []
  const acc = () => {
    const a = alloc()
    accounts.push(a)
    return a
  }
  const add = (at: number, from: string, to: string, amount: number) => steps.push({ at, from, to, amount })

  switch (id) {
    case 'FAN_OUT': {
      const origin = acc()
      const source = acc()
      const mules = Array.from({ length: 12 }, acc)
      const cash = [acc(), acc()]
      add(0, origin, source, rupees(300_000))
      mules.forEach((m, i) => {
        const amt = jitter(rand, rupees(24_000), 0.02)
        add(2_000 + i * 1_400, source, m, amt)
        if (i >= 8) add(2_000 + i * 1_400 + 4_000, m, cash[i % 2], Math.round(amt * 0.97))
      })
      break
    }
    case 'PASS_THROUGH': {
      const feeders = Array.from({ length: 8 }, acc)
      const [b, c, d, e] = [acc(), acc(), acc(), acc()]
      let total = 0
      feeders.forEach((f, i) => {
        const amt = jitter(rand, rupees(7_000), 0.12)
        total += amt
        add(i * 1_000, f, b, amt)
      })
      const b2c = Math.round(total * 0.96)
      const c2d = Math.round(b2c * 0.97)
      add(11_000, b, c, b2c)
      add(15_000, c, d, c2d)
      add(19_000, d, e, Math.round(c2d * 0.97))
      break
    }
    case 'CYCLE': {
      const feeders = Array.from({ length: 6 }, acc)
      const [a, b, c, d] = [acc(), acc(), acc(), acc()]
      let total = 0
      feeders.forEach((f, i) => {
        const amt = jitter(rand, rupees(10_000), 0.08)
        total += amt
        add(i * 1_000, f, a, amt)
      })
      let amt = Math.round(total * 0.97)
      const ring = [a, b, c, d, a]
      for (let i = 0; i < 4; i++) {
        add(8_000 + i * 4_000, ring[i], ring[i + 1], amt)
        amt = Math.round(amt * 0.975)
      }
      break
    }
    case 'MULTI_HOP': {
      const feeders = Array.from({ length: 8 }, acc)
      const origin = acc()
      const layers = [0, 1, 2].map(() => [acc(), acc(), acc()])
      const sink = acc()
      let total = 0
      feeders.forEach((f, i) => {
        const amt = jitter(rand, rupees(9_000), 0.08)
        total += amt
        add(i * 1_000, f, origin, amt)
      })
      const branch = Math.round((total * 0.97) / 3)
      for (let k = 0; k < 3; k++) {
        let amt = jitter(rand, branch, 0.01)
        let prev = origin
        for (let h = 0; h < 3; h++) {
          add(10_000 + h * 5_000 + k * 1_000, prev, layers[h][k], amt)
          prev = layers[h][k]
          amt = Math.round(amt * 0.975)
        }
        add(25_000 + k * 1_000, prev, sink, amt)
      }
      break
    }
    case 'MULE_NETWORK': {
      const victims = Array.from({ length: 8 }, acc)
      const collector = acc()
      const mules = Array.from({ length: 12 }, acc)
      const layer = [acc(), acc(), acc()]
      const consolidator = acc()
      const exit = acc()
      let total = 0
      victims.forEach((v, i) => {
        const amt = jitter(rand, rupees(15_000), 0.2)
        total += amt
        add(i * 900, v, collector, amt)
      })
      const split = Math.round((total * 0.95) / 12)
      const layerIn = [0, 0, 0]
      mules.forEach((m, i) => {
        const amt = jitter(rand, split, 0.015)
        const t = 9_000 + i * 1_200
        add(t, collector, m, amt)
        const fwd = Math.round(amt * 0.97)
        layerIn[i % 3] += fwd
        add(t + 4_500, m, layer[i % 3], fwd)
      })
      let consolidated = 0
      layer.forEach((l, i) => {
        const amt = Math.round(layerIn[i] * 0.97)
        consolidated += amt
        add(29_000 + i * 1_500, l, consolidator, amt)
      })
      add(36_000, consolidator, exit, Math.round(consolidated * 0.96))
      break
    }
  }
  steps.sort((a, b) => a.at - b.at)
  return { steps, accounts }
}
