import { ArrowLeft, ChevronDown, Command, Ellipsis, Network, PanelLeft, Plus, RefreshCw, Search, Bell, Sparkles, ListTree, Activity, ShieldExclamationPoint, Users, LayoutGrid, Redo2, Undo2, FileClock, Settings2 } from 'lucide-react'

/**
 * Hero product preview — a dark VeriFlow console rendered with live SVG
 * (mirrors the reference composition: sidebar · canvas · inspector).
 */
export default function HeroConsole() {
  return (
    <div className="relative overflow-hidden rounded-[14px] border border-white/10 bg-[#0e0d0c] text-white shadow-[0_40px_120px_-20px_rgba(0,0,0,0.9)]">
      <div className="grid grid-cols-[176px_1fr] max-md:grid-cols-1">
        {/* Sidebar */}
        <aside className="flex flex-col border-r border-white/[0.06] bg-[#111010] px-3 py-3 max-md:hidden">
          <div className="flex items-center justify-between px-1">
            <span className="flex items-center gap-1.5 text-[11px] font-semibold">
              <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden>
                <circle cx="12" cy="12" r="12" fill="#fff" />
                <path d="M6.6 7.4 L12 16.8 L17.4 7.4" fill="none" stroke="#0d0c0b" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              VeriFlow
            </span>
            <PanelLeft className="size-3 text-white/40" />
          </div>
          <div className="mt-3 flex items-center gap-1.5 rounded-[6px] border border-white/[0.07] bg-white/[0.02] px-2 py-1.5 text-[9.5px] text-white/40">
            <Search className="size-2.5" /> Search…
            <span className="ml-auto flex items-center gap-0.5 text-white/30">
              <Command className="size-2" />K
            </span>
          </div>
          <p className="mt-4 px-1 text-[8px] font-medium tracking-[0.12em] text-white/35">MONITOR</p>
          <nav className="mt-1.5 space-y-0.5 text-[10px] text-white/60">
            {[
              [LayoutGrid, 'Overview'],
              [Network, 'Live Network', true],
              [ListTree, 'Transactions'],
              [ShieldExclamationPoint, 'Risk Signals'],
              [Users, 'Accounts'],
            ].map(([Icon, label, active]: any) => (
              <div key={label} className={`flex items-center gap-2 rounded-[5px] px-1.5 py-1 ${active ? 'bg-white/[0.06] text-white' : ''}`}>
                <Icon className="size-3" strokeWidth={1.6} /> {label}
              </div>
            ))}
          </nav>
          <div className="mt-4 flex items-center justify-between px-1">
            <p className="text-[8px] font-medium tracking-[0.12em] text-white/35">CASES</p>
            <span className="grid size-3.5 place-items-center rounded-full bg-[#efc8a9] text-[#1a120c]">
              <Plus className="size-2.5" strokeWidth={2.5} />
            </span>
          </div>
          <div className="relative mt-1.5 space-y-0.5 text-[10px] text-white/60">
            <span className="absolute -left-3 top-1 h-4 w-[2px] rounded-full bg-white/70" />
            {['Mule Ring 07', 'Fan-out · ACC204', 'Layering Chain', 'Circular Ring'].map((l, i) => (
              <div key={l} className={`flex items-center gap-2 rounded-[5px] px-1.5 py-1 ${i === 0 ? 'text-white' : ''}`}>
                <span className="text-white/30">⋮⋮</span> {l} <ChevronDown className="ml-auto size-2.5 text-white/30" />
              </div>
            ))}
          </div>
          <div className="mt-auto space-y-0.5 pt-10 text-[10px] text-white/25">
            <p className="px-1 pb-1 text-[8px] tracking-[0.12em]">TOOLS</p>
            <div className="flex items-center gap-2 px-1.5 py-1">
              <FileClock className="size-3" /> Audit Trail
            </div>
            <div className="flex items-center gap-2 px-1.5 py-1">
              <Settings2 className="size-3" /> Settings
            </div>
          </div>
        </aside>

        {/* Main */}
        <div className="min-w-0">
          <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-2.5 text-[10px]">
            <span className="text-white/45">
              Console <span className="mx-1 text-white/20">/</span> Live Network <span className="mx-1 text-white/20">/</span>
              <span className="text-white/80">Mule Ring 07</span>
            </span>
            <span className="flex items-center gap-2 text-white/60">
              <Bell className="size-3" />
              <span className="flex items-center gap-1 rounded-full border border-white/10 px-2 py-0.5 text-[9.5px] text-white/80">
                Simulate <Sparkles className="size-2.5" />
              </span>
              <span className="size-4 rounded-full bg-gradient-to-br from-[#efc8a9] to-[#7a5a44]" />
            </span>
          </div>

          <div className="m-3 overflow-hidden rounded-[10px] border border-white/[0.07] bg-[#131211]">
            <div className="flex items-center justify-between border-b border-white/[0.06] px-3 py-2 text-[10px]">
              <span className="flex items-center gap-2 text-white/85">
                <ArrowLeft className="size-3 text-white/50" /> Mule Network
                <span className="rounded-[3px] bg-[#efc8a9] px-1 py-[1px] text-[7.5px] font-semibold tracking-wide text-[#1a120c]">ESCALATE</span>
              </span>
              <span className="flex items-center gap-2 text-white/50 max-sm:hidden">
                <RefreshCw className="size-2.5" /> Synced just now
                <span className="flex -space-x-1">
                  {['#efc8a9', '#cfa184', '#a07b62'].map((c) => (
                    <span key={c} className="size-3.5 rounded-full border border-[#131211]" style={{ background: c }} />
                  ))}
                </span>
                <span className="rounded-full border border-white/10 px-2 py-0.5 text-white/75">Export</span>
                <span className="rounded-full border border-white/10 px-2 py-0.5 text-white/75">Open Case</span>
                <Ellipsis className="size-3" />
              </span>
            </div>
            <div className="grid grid-cols-[1fr_190px] max-lg:grid-cols-1">
              <Canvas />
              <Inspector />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

type CardProps = { x: number; y: number; w?: number; title: string; sub: string; tag?: string; hot?: boolean; delay?: number; faded?: boolean }
function Card({ x, y, w = 112, title, sub, tag, hot, delay = 0, faded }: CardProps) {
  return (
    <g transform={`translate(${x} ${y})`} opacity={faded ? 0.35 : 1}>
      <rect width={w} height="46" rx="6" fill="#1a1816" stroke="#2c2926" />
      {hot && (
        <rect width={w} height="46" rx="6" fill="none" stroke="#efc8a9" strokeWidth="1.2" opacity="0">
          <animate attributeName="opacity" values="0;0.95;0.95;0" keyTimes="0;0.15;0.7;1" dur="6s" begin={`${delay}s`} repeatCount="indefinite" />
        </rect>
      )}
      <line x1="0" x2={w} y1="20" y2="20" stroke="#262320" />
      <circle cx="11" cy="10" r="4.5" fill="#efc8a9" opacity="0.9" />
      <text x="20" y="13" fontSize="7.5" fill="#efeae4" fontWeight="600">
        {title}
      </text>
      <text x={w - 9} y="13" fontSize="8" fill="#6d6762">
        ⋮
      </text>
      <text x="9" y="34" fontSize="7" fill="#9a938d">
        {sub}
      </text>
      {tag && (
        <g transform={`translate(${w - 34} 27)`}>
          <rect width="26" height="11" rx="2.5" fill="#262320" />
          <text x="13" y="8" fontSize="6" fill="#c9c2bb" textAnchor="middle">
            {tag}
          </text>
        </g>
      )}
    </g>
  )
}

function Label({ x, y, t }: { x: number; y: number; t: string }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <rect x={-t.length * 2.1 - 4} y="-6" width={t.length * 4.2 + 8} height="11" rx="2.5" fill="#211f1c" stroke="#302c29" />
      <text y="2.5" fontSize="6" fill="#bdb6af" textAnchor="middle" className="tabular">
        {t}
      </text>
    </g>
  )
}

const PATHS = {
  a: 'M 128 66 L 128 92 L 160 92',
  b: 'M 272 115 L 296 115 L 296 70 L 320 70',
  c: 'M 272 115 L 320 115',
  d: 'M 272 115 L 296 115 L 296 160 L 320 160',
  e: 'M 432 70 L 456 70 L 456 115 L 478 115',
  f: 'M 432 115 L 478 115',
  g: 'M 432 160 L 456 160 L 456 115 L 478 115',
  h: 'M 534 138 L 534 196',
  i: 'M 128 66 L 128 236',
}

function Pulse({ path, dur, begin }: { path: string; dur: number; begin: number }) {
  return (
    <circle r="2.2" fill="#efc8a9">
      <animateMotion path={path} dur={`${dur}s`} begin={`${begin}s`} repeatCount="indefinite" />
      <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.85;1" dur={`${dur}s`} begin={`${begin}s`} repeatCount="indefinite" />
    </circle>
  )
}

function Canvas() {
  return (
    <div className="dot-grid relative min-h-[300px] border-r border-white/[0.06] max-lg:border-r-0">
      <div className="absolute left-3 top-3 flex gap-1.5">
        <span className="grid size-5 place-items-center rounded-full bg-[#efc8a9] text-[#1a120c]">
          <Undo2 className="size-2.5" strokeWidth={2.4} />
        </span>
        <span className="grid size-5 place-items-center rounded-full bg-white/[0.06] text-white/60">
          <Redo2 className="size-2.5" />
        </span>
      </div>
      <div className="absolute right-3 top-3 flex items-center gap-2 rounded-full bg-[#efc8a9] px-2.5 py-0.5 text-[9px] font-medium text-[#1a120c]">
        <span>–</span> 80% <span>+</span>
      </div>
      <svg viewBox="0 0 640 300" className="h-full w-full" role="img" aria-label="Animated mule network detection preview">
        <g fill="none" stroke="#3a3632" strokeWidth="1">
          {Object.values(PATHS).map((d) => (
            <path key={d} d={d} />
          ))}
        </g>
        <g fill="none" stroke="#efc8a9" strokeWidth="1" strokeDasharray="3 5" opacity="0.55" className="anim-dash">
          <path d={PATHS.b} />
          <path d={PATHS.e} />
        </g>
        <Pulse path={PATHS.a} dur={2.4} begin={0} />
        <Pulse path={PATHS.b} dur={2} begin={0.8} />
        <Pulse path={PATHS.c} dur={1.6} begin={1.2} />
        <Pulse path={PATHS.d} dur={2} begin={1.6} />
        <Pulse path={PATHS.e} dur={2} begin={2.4} />
        <Pulse path={PATHS.g} dur={2} begin={2.8} />
        <Pulse path={PATHS.h} dur={1.8} begin={3.4} />

        <Card x={72} y={22} title="Victims ×8" sub="Inbound UPI · 9s" tag="₹1.2L" />
        <Card x={160} y={92} title="Collector" sub="ACC209 · fan-in 8" tag="FAN_IN" hot delay={0.4} />
        <Card x={320} y={47} title="Mule" sub="ACC212 · held 4s" />
        <Card x={320} y={92} title="Mule" sub="ACC213 · held 5s" hot delay={1.6} />
        <Card x={320} y={137} title="Mule" sub="ACC214 · held 4s" />
        <Card x={478} y={92} w={112} title="Consolidator" sub="ACC225 · 97% fwd" tag="ESC" hot delay={2.8} />
        <Card x={72} y={236} title="Evaluate" sub="Path 1 · 0.08 ms" faded />
        <Card x={200} y={236} title="Outcome" sub="SUCCESS · stream" faded />
        <Card x={328} y={236} title="Confirm" sub="Redis graph" faded />

        <Label x={296} y={92} t="₹9.5K ×12" />
        <Label x={456} y={92} t="97%" />
        <Label x={128} y={80} t="8 senders" />
        <g transform="translate(486 196)">
          <rect width="96" height="20" rx="10" fill="#1a1816" stroke="#2c2926" />
          <circle cx="11" cy="10" r="4" fill="#efc8a9" />
          <text x="20" y="13" fontSize="7" fill="#d8d1ca">
            Exit · ACC226
          </text>
        </g>
        <g className="anim-float">
          <g transform="translate(212 150)">
            <path d="M0 0 L7 3 L3.5 4 L2 8 Z" fill="#fff" />
            <rect x="6" y="9" width="54" height="15" rx="7.5" fill="#efeae4" />
            <text x="33" y="19" fontSize="6.5" fill="#1a1816" textAnchor="middle" fontWeight="600">
              4-hop path
            </text>
          </g>
        </g>
      </svg>
    </div>
  )
}

function Inspector() {
  const rows: [string, string, string][] = [
    ['FAN_IN', '1.00', '#4cc27e'],
    ['FAN_OUT', '1.00', '#4cc27e'],
    ['PASS_THROUGH', '0.97', '#f07067'],
    ['MULTI_HOP', '4 hops', '#f07067'],
  ]
  return (
    <div className="p-3 text-[9.5px] max-lg:hidden">
      <div className="flex items-center gap-2 text-[11px] font-medium">
        <span className="grid size-5 place-items-center rounded-[5px] border border-white/10 bg-white/[0.04]">
          <Activity className="size-3 text-white/70" />
        </span>
        ACC209
      </div>
      <div className="mt-2.5 flex items-center justify-between rounded-[6px] border border-white/[0.07] bg-white/[0.02] px-2 py-1.5 text-white/70">
        Collector · 14 days <span className="text-white/30">✎</span>
      </div>
      <p className="mt-3 font-medium text-white/85">Signals</p>
      <p className="text-[8.5px] text-white/35">Weighted evidence</p>
      <div className="mt-2 space-y-1.5 rounded-[7px] border border-white/[0.07] bg-[#171513] p-2">
        {rows.map(([k, v, c]) => (
          <div key={k} className="flex items-center gap-2">
            <span className="size-1.5 rounded-full" style={{ background: c }} />
            <span className="font-mono text-[8.5px] text-white/70">{k}</span>
            <span className="tabular ml-auto text-white/85">{v}</span>
          </div>
        ))}
      </div>
      <div className="mt-2.5 flex items-center justify-between rounded-[6px] border border-white/[0.07] px-2 py-1.5">
        <span className="text-white/60">Risk score</span>
        <span className="tabular text-[12px] font-semibold text-[#efc8a9]">84.6</span>
      </div>
      <div className="mt-2 flex items-center justify-between text-white/50">
        Decision <span className="rounded-[3px] bg-[#341716] px-1.5 py-[1px] text-[8px] font-semibold text-[#f07067]">ESCALATE</span>
      </div>
      <div className="mt-3 space-y-1.5 opacity-60">
        {[
          ['unique_receivers_30s', '12'],
          ['pass_through_ratio', '0.95'],
          ['holding_time_sec', '10.3'],
        ].map(([k, v]) => (
          <div key={k} className="flex justify-between rounded-[5px] border border-white/[0.06] px-2 py-1 font-mono text-[8px]">
            <span className="text-white/50">{k}</span>
            <span className="text-white/80">{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
