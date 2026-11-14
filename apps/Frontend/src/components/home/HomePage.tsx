import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import {
  ArrowRight,
  ArrowUpRight,
  Boxes,
  Database,
  GitBranch,
  GitFork,
  Layers,
  Network,
  Play,
  Radar,
  Repeat,
  Route,
  ScanSearch,
  Server,
  Share2,
  ShieldCheck,
  Split,
  Workflow,
  Zap,
  Merge,
  Gauge,
} from 'lucide-react'
import { Logo, LogoMark } from '../brand/Logo'
import { blurIn, EASE, Reveal, stagger } from '../ui/Reveal'
import HeroConsole from './HeroConsole'
import { CycleDiagram, FanInDiagram, FanOutDiagram, MultiHopDiagram, PassThroughDiagram } from './MiniDiagrams'
import { navigate } from '../../lib/router'

const HERO_IMG = 'https://images.unsplash.com/photo-1733976864002-a3baeb00f25a?auto=format&fit=crop&w=2400&q=80'
const toConsole = () => navigate('#/console/overview')

export default function HomePage() {
  return (
    <div className="min-h-dvh bg-black text-white">
      <Nav />
      <Hero />
      <TechStrip />
      <Platform />
      <Detection />
      <Architecture />
      <FinalCTA />
      <Footer />
    </div>
  )
}

/* ------------------------------- Nav ------------------------------- */
function Nav() {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 24)
    on()
    window.addEventListener('scroll', on, { passive: true })
    return () => window.removeEventListener('scroll', on)
  }, [])
  const links: [string, string][] = [
    ['Product', '#/platform'],
    ['Detection', '#/detection'],
    ['Architecture', '#/architecture'],
    ['Docs', '#/architecture'],
  ]
  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-[background-color,backdrop-filter,border-color] duration-500 ${
        scrolled ? 'border-b border-white/[0.06] bg-black/55 backdrop-blur-xl' : 'border-b border-transparent'
      }`}
    >
      <div className="mx-auto flex h-16 max-w-[1240px] items-center px-6">
        <a href="#/" aria-label="VeriFlow home" className="flex h-9 items-center">
          <Logo />
        </a>
        <nav className="ml-14 hidden h-9 items-center gap-7 md:flex">
          {links.map(([l, h]) => (
            <a key={l} href={h} className="flex h-9 items-center text-[13px] leading-none text-white/75 transition-colors duration-300 hover:text-white">
              {l}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex h-9 items-center gap-2">
          <button
            onClick={() => navigate('#/console/settings')}
            className="hidden h-9 items-center rounded-full border border-white/20 px-4 text-[13px] leading-none text-white/90 transition-colors duration-300 hover:border-white/40 sm:flex"
          >
            Connect API
          </button>
          <button
            onClick={toConsole}
            className="flex h-9 items-center rounded-full border border-white bg-white px-4 text-[13px] font-medium leading-none text-black transition-transform duration-300 hover:scale-[1.03]"
          >
            Open Console
          </button>
        </div>
      </div>
    </header>
  )
}

/* ------------------------------- Hero ------------------------------- */
function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="absolute inset-0 h-[920px]">
        <img src={HERO_IMG} alt="" className="h-full w-full scale-[1.04] object-cover object-[50%_62%]" fetchPriority="high" />
        <div className="absolute inset-0 bg-gradient-to-b from-[#0b1218]/55 via-transparent to-black" />
        <div className="absolute inset-x-0 bottom-0 h-[420px] bg-gradient-to-b from-transparent via-black/80 to-black" />
      </div>

      <motion.div
        initial="hidden"
        animate="show"
        variants={stagger(0.09, 0.15)}
        className="relative mx-auto flex max-w-[1240px] flex-col items-center px-6 pt-36 text-center"
      >
        <motion.span variants={blurIn} className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-black/25 py-1 pl-1 pr-3 text-[10.5px] font-medium tracking-[0.08em] text-white/85 backdrop-blur-md">
          <span className="grid size-5 place-items-center rounded-full bg-white text-black">
            <Gauge className="size-3" strokeWidth={2} />
          </span>
          SUB-100MS P95 TARGET
        </motion.span>
        <motion.h1 variants={blurIn} className="mt-7 font-serif text-[clamp(44px,6.4vw,80px)] font-light leading-[1.02] tracking-[-0.025em] text-white">
          See the network behind
          <br />
          every transaction
        </motion.h1>
        <motion.p variants={blurIn} className="mt-6 max-w-[520px] text-[15px] leading-relaxed text-white/75">
          Real-time graph intelligence for money mule and collusion detection.
        </motion.p>
        <motion.div variants={blurIn} className="mt-8 flex flex-col items-center gap-4">
          <button
            onClick={toConsole}
            className="group inline-flex items-center gap-2 rounded-full bg-black px-6 py-3 text-[14px] text-white ring-1 ring-white/10 transition-[transform,box-shadow] duration-500 hover:scale-[1.03] hover:shadow-[0_0_0_6px_rgba(255,255,255,0.06)]"
          >
            Launch Live Engine
            <ArrowRight className="size-4 transition-transform duration-500 group-hover:translate-x-0.5" />
          </button>
          <a href="#/architecture" className="inline-flex items-center gap-2 text-[12.5px] text-white/75 transition-colors hover:text-white">
            <Play className="size-3" /> Discover the technology
          </a>
        </motion.div>
      </motion.div>

      {/* Floating callouts with connector curves */}
      <div className="pointer-events-none absolute inset-x-0 top-[470px] mx-auto hidden h-[260px] max-w-[1440px] lg:block">
        <svg className="absolute left-0 top-0 h-full w-[260px]" viewBox="0 0 260 260" fill="none">
          <path d="M0 40 C 60 40 70 70 120 70 L 150 70" stroke="rgba(255,255,255,0.28)" />
          <path d="M40 260 C 40 200 60 180 120 180" stroke="rgba(255,255,255,0.18)" />
        </svg>
        <svg className="absolute right-0 top-0 h-full w-[260px]" viewBox="0 0 260 260" fill="none">
          <path d="M260 20 C 200 20 190 110 130 110 L 110 110" stroke="rgba(255,255,255,0.28)" />
          <path d="M220 260 C 220 200 200 190 150 190" stroke="rgba(255,255,255,0.18)" />
        </svg>
        <motion.div initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.9, duration: 0.8, ease: EASE }} className="absolute left-[150px] top-[56px]">
          <Callout icon={<Split className="size-3" />} text="Fan-out detected" />
        </motion.div>
        <motion.div initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 1.05, duration: 0.8, ease: EASE }} className="absolute right-[110px] top-[96px]">
          <Callout icon={<Route className="size-3" />} text="4-hop mule chain" />
        </motion.div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 40, filter: 'blur(10px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ delay: 0.55, duration: 1.1, ease: EASE }}
        className="relative mx-auto mt-16 max-w-[1080px] px-6 lg:mt-24"
      >
        <HeroConsole />
        <div className="pointer-events-none absolute inset-x-6 bottom-0 h-24 bg-gradient-to-b from-transparent to-black" />
      </motion.div>
    </section>
  )
}

function Callout({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <span className="anim-float inline-flex items-center gap-2 rounded-full border border-white/15 bg-black/45 py-1 pl-1 pr-3 text-[11.5px] text-white/90 backdrop-blur-md">
      <span className="grid size-5 place-items-center rounded-full bg-white text-black">{icon}</span>
      {text}
    </span>
  )
}

/* ---------------------------- Tech strip ---------------------------- */
function TechStrip() {
  const items: [React.ReactNode, string][] = [
    [<Server key="n" className="size-4" />, 'Node.js'],
    [<Zap key="r" className="size-4" />, 'Redis Streams'],
    [<Gauge key="f" className="size-4" />, 'FastAPI'],
    [<Database key="p" className="size-4" />, 'PostgreSQL'],
    [<Layers key="pr" className="size-4" />, 'Prisma'],
    [<Boxes key="py" className="size-4" />, 'Python'],
    [<Share2 key="c" className="size-4" />, 'Cytoscape.js'],
  ]
  const group = (copy: number) => (
    <div className="flex shrink-0 items-center gap-16 pr-16" aria-hidden={copy > 0 || undefined}>
      {items.map(([icon, label]) => (
        <span key={label} className="flex items-center gap-2 whitespace-nowrap text-[17px] font-semibold tracking-[-0.01em] text-white/40 transition-colors duration-300 hover:text-white/80">
          {icon}
          {label}
        </span>
      ))}
    </div>
  )
  return (
    <div className="group/strip relative mx-auto mt-10 max-w-[1080px] overflow-hidden px-6 [mask-image:linear-gradient(90deg,transparent,#000_12%,#000_88%,transparent)]">
      {/* Two identical groups translated by exactly one group width → seamless loop */}
      <div className="anim-marquee flex w-max py-4 group-hover/strip:[animation-play-state:paused]">
        {group(0)}
        {group(1)}
      </div>
    </div>
  )
}

/* ------------------------------ Section head ------------------------------ */
function SectionHead({ id, tag, icon, title, aside }: { id: string; tag: string; icon: React.ReactNode; title: React.ReactNode; aside: string }) {
  return (
    <div id={id} className="scroll-mt-24">
      <Reveal>
        <span className="inline-flex items-center gap-2 rounded-full border border-white/15 py-1 pl-1 pr-3 text-[10.5px] font-medium tracking-[0.1em] text-white/80">
          <span className="grid size-5 place-items-center rounded-full bg-white text-black">{icon}</span>
          {tag}
        </span>
      </Reveal>
      <div className="mt-8 flex flex-col justify-between gap-6 md:flex-row md:items-end">
        <Reveal delay={0.05}>
          <h2 className="font-serif text-[clamp(36px,4.4vw,56px)] font-light leading-[1.04] tracking-[-0.02em]">{title}</h2>
        </Reveal>
        <Reveal delay={0.1}>
          <p className="max-w-[300px] text-[14px] leading-relaxed text-white/60">{aside}</p>
        </Reveal>
      </div>
    </div>
  )
}

const card = 'relative overflow-hidden rounded-[14px] border border-white/[0.07] bg-[#0d0c0b]'

/* ------------------------------ Platform bento ------------------------------ */
function Platform() {
  return (
    <section className="mx-auto max-w-[1240px] px-6 pt-36">
      <SectionHead id="platform" tag="PLATFORM" icon={<Radar className="size-3" />} title={<>Intelligence for<br />every transfer</>} aside="Relationships expose what single transactions hide." />
      <div className="mt-14 grid gap-4 md:grid-cols-3">
        <Reveal className={`${card} dot-grid min-h-[300px] p-7`}>
          <svg className="absolute inset-0 h-full w-full" viewBox="0 0 400 300" preserveAspectRatio="none" fill="none">
            <path d="M0 230 C 120 230 140 120 260 120 C 330 120 360 60 400 40" stroke="rgba(255,255,255,0.12)" />
          </svg>
          <div className="relative flex h-[170px] items-center justify-center">
            <motion.span whileHover={{ scale: 1.06 }} className="grid size-16 place-items-center rounded-full bg-[#efc8a9] text-[#1a120c] shadow-[0_0_0_10px_rgba(239,200,169,0.12)]">
              <Network className="size-6" strokeWidth={1.6} />
            </motion.span>
            <span className="absolute left-[58%] top-[64%] h-px w-12 rotate-[35deg] bg-[#efc8a9]/70" />
            <span className="absolute left-[66%] top-[72%] grid size-10 place-items-center rounded-full bg-[#efc8a9] text-[#1a120c]">
              <Share2 className="size-4" />
            </span>
          </div>
          <BentoText title="Graph Intelligence" text="Directed, weighted, temporal multigraph." />
        </Reveal>

        <Reveal delay={0.06} className={`${card} dot-grid min-h-[300px] p-7 md:col-span-2`}>
          <div className="relative flex flex-wrap items-center gap-y-6 pt-4">
            <FlowCard icon={<Workflow className="size-3" />} title="Proposed" body="TXN1001 · ₹25,000" />
            <Connector />
            <FlowCard icon={<ScanSearch className="size-3" />} title="Evaluate" body="Bounded 4-hop snapshot" />
            <Connector />
            <FlowCard icon={<ShieldCheck className="size-3" />} title="Decision" body="Risk 82.5" chips={['ESCALATE']} />
            <span className="absolute -bottom-2 left-[62%] inline-flex items-center gap-1.5 rounded-full bg-[#efeae4] px-2.5 py-1 text-[10.5px] font-medium text-black">
              <span className="size-1.5 rounded-full bg-[#d6453d]" /> explainable
            </span>
          </div>
          <div className="absolute bottom-7 left-7 right-7">
            <BentoText title="Transaction Risk Analysis" text="Score every candidate edge before settlement." />
          </div>
        </Reveal>

        <Reveal delay={0.04} className={`${card} dot-grid min-h-[300px] p-7 md:col-span-2`}>
          <div className="grid grid-cols-3 gap-6 opacity-95">
            <div className="h-[150px]">
              <FanInDiagram />
            </div>
            <div className="h-[150px]">
              <PassThroughDiagram />
            </div>
            <div className="h-[150px]">
              <FanOutDiagram />
            </div>
          </div>
          <div className="absolute bottom-7 left-7 right-7">
            <BentoText title="Money Mule Detection" text="Collect, forward, split — caught as one flow." />
          </div>
        </Reveal>

        <Reveal delay={0.1} className={`${card} dot-grid min-h-[300px] p-7`}>
          <div className="relative h-[170px]">
            <ClusterDiagram />
          </div>
          <BentoText title="Fraud Network Discovery" text="Suspicious subgraphs surface automatically." />
        </Reveal>
      </div>
    </section>
  )
}

function ClusterDiagram() {
  const nodes = [
    [100, 80, 1],
    [60, 40, 0],
    [150, 40, 0],
    [40, 110, 0],
    [160, 120, 1],
    [110, 140, 0],
    [200, 80, 0],
  ] as const
  const edges = [
    [0, 1],
    [0, 2],
    [0, 3],
    [0, 4],
    [4, 5],
    [4, 6],
    [2, 6],
  ]
  return (
    <svg viewBox="0 0 240 170" className="h-full w-full" aria-label="Highlighted suspicious subgraph">
      {edges.map(([a, b], i) => (
        <line key={i} x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]} stroke={nodes[a][2] && nodes[b][2] ? '#efc8a9' : '#3a3632'} strokeDasharray={i === 3 ? '3 4' : undefined} className={i === 3 ? 'anim-dash' : undefined} />
      ))}
      <circle cx="130" cy="100" r="62" fill="none" stroke="#efc8a9" strokeOpacity="0.25" strokeDasharray="2 5" />
      {nodes.map(([x, y, hot], i) => (
        <circle key={i} cx={x} cy={y} r={hot ? 8 : 5} fill={hot ? '#efc8a9' : '#1c1a18'} stroke={hot ? '#efc8a9' : '#4a4540'} />
      ))}
    </svg>
  )
}

function BentoText({ title, text }: { title: string; text: string }) {
  return (
    <div className="relative mt-6">
      <h3 className="text-[17px] font-medium tracking-[-0.01em]">{title}</h3>
      <p className="mt-1.5 text-[13.5px] text-white/55">{text}</p>
    </div>
  )
}

function FlowCard({ icon, title, body, chips }: { icon: React.ReactNode; title: string; body: string; chips?: string[] }) {
  return (
    <div className="w-[190px] rounded-[9px] border border-white/[0.09] bg-[#161412] transition-colors duration-500 hover:border-[#efc8a9]/50">
      <div className="flex items-center gap-2 border-b border-white/[0.07] px-3 py-2 text-[12.5px] font-medium">
        <span className="grid size-5 place-items-center rounded-full bg-[#efc8a9] text-[#1a120c]">{icon}</span>
        {title}
        <span className="ml-auto text-white/35">⋮</span>
      </div>
      <div className="px-3 py-2.5 text-[12px] text-white/70">
        {body}
        {chips && (
          <div className="mt-2 flex gap-1">
            {chips.map((c) => (
              <span key={c} className="rounded-[4px] bg-[#341716] px-1.5 py-[1px] text-[9.5px] font-semibold text-[#f07067]">
                {c}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
function Connector() {
  return (
    <span className="relative mx-3 h-px w-10 bg-white/25 max-sm:hidden">
      <motion.span
        className="absolute -top-[2px] size-[5px] rounded-full bg-[#efc8a9]"
        animate={{ left: ['0%', '100%'], opacity: [0, 1, 0] }}
        transition={{ duration: 1.6, repeat: Infinity, ease: 'linear' }}
      />
    </span>
  )
}

/* ------------------------------ Detection modules ------------------------------ */
const MODULES = [
  { key: 'FAN_OUT', title: 'Fan-Out', icon: <Split className="size-3.5" />, text: 'One account, many receivers, fast.', metric: 'unique_receivers_30s', weight: '0.20', Diagram: FanOutDiagram },
  { key: 'FAN_IN', title: 'Fan-In', icon: <Merge className="size-3.5" />, text: 'Many senders converge on one.', metric: 'unique_senders_60s', weight: '0.20', Diagram: FanInDiagram },
  { key: 'RAPID_PASS_THROUGH', title: 'Pass-Through', icon: <ArrowUpRight className="size-3.5" />, text: 'Received, then forwarded in seconds.', metric: 'pass_through_ratio', weight: '0.25', Diagram: PassThroughDiagram },
  { key: 'CYCLE', title: 'Cycle Detection', icon: <Repeat className="size-3.5" />, text: 'Funds return to their origin.', metric: 'cycle_length ≤ 4', weight: '0.15', Diagram: CycleDiagram },
  { key: 'MULTI_HOP', title: 'Multi-Hop', icon: <GitBranch className="size-3.5" />, text: 'Layered chains across intermediaries.', metric: 'max_path_depth', weight: '0.20', Diagram: MultiHopDiagram },
]

function Detection() {
  return (
    <section className="mx-auto max-w-[1240px] px-6 pt-40">
      <SectionHead id="detection" tag="DETECTION" icon={<ScanSearch className="size-3" />} title={<>Five patterns.<br />One decision.</>} aside="Weighted signals, combined into an explainable 0–100 score." />
      <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
        {MODULES.map((m, i) => (
          <Reveal key={m.key} delay={i * 0.05} className={`${card} group p-5 ${i < 2 ? 'lg:col-span-3' : 'lg:col-span-2'} transition-colors duration-500 hover:border-white/15`}>
            <div className={`dot-grid rounded-[10px] border border-white/[0.05] bg-black/30 ${i < 2 ? 'h-[180px]' : 'h-[150px]'}`}>
              <m.Diagram />
            </div>
            <div className="mt-5 flex items-center gap-2.5">
              <span className="grid size-7 place-items-center rounded-full bg-[#efc8a9] text-[#1a120c]">{m.icon}</span>
              <h3 className="text-[16px] font-medium">{m.title}</h3>
              <span className="tabular ml-auto font-mono text-[11px] text-white/40">w {m.weight}</span>
            </div>
            <p className="mt-2 text-[13.5px] text-white/55">{m.text}</p>
            <p className="mt-4 inline-block rounded-[5px] border border-white/[0.08] px-2 py-1 font-mono text-[10.5px] text-white/50">{m.metric}</p>
          </Reveal>
        ))}
      </div>
      <Reveal delay={0.1} className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-[14px] border border-white/[0.07] bg-white/[0.07] md:grid-cols-4">
        {(
          [
            ['ALLOW', '0–29', '#4cc27e'],
            ['MONITOR', '30–59', '#7ea2f5'],
            ['REVIEW', '60–79', '#e2b04a'],
            ['ESCALATE', '80–100', '#f07067'],
          ] as const
        ).map(([d, r, c]) => (
          <div key={d} className="flex items-center justify-between bg-[#0d0c0b] px-6 py-5">
            <span className="flex items-center gap-2.5 text-[13px] font-medium tracking-[0.04em]">
              <span className="size-2 rounded-full" style={{ background: c }} />
              {d}
            </span>
            <span className="tabular font-mono text-[12px] text-white/45">{r}</span>
          </div>
        ))}
      </Reveal>
    </section>
  )
}

/* ------------------------------ Architecture ------------------------------ */
function Architecture() {
  const path1 = [
    ['Transaction Event', 'PENDING'],
    ['Ingestion', 'Node.js · validate'],
    ['Risk Evaluation', 'FastAPI'],
    ['Graph Analysis', 'BFS · DFS · 4 hops'],
    ['Fraud Signals', '5 modules'],
    ['Risk Decision', 'ALLOW → ESCALATE'],
  ]
  const path2 = [
    ['Outcome', 'SUCCESS only'],
    ['Redis Streams', 'XADD · consumer group'],
    ['Graph Worker', 'idempotent'],
    ['Confirmed Graph', 'Redis ZSET'],
    ['PostgreSQL', 'Prisma · audit'],
  ]
  return (
    <section className="mx-auto max-w-[1240px] px-6 pt-40">
      <SectionHead id="architecture" tag="ARCHITECTURE" icon={<Workflow className="size-3" />} title={<>Two paths.<br />Never mixed.</>} aside="Candidates are scored. Only confirmed outcomes become edges." />
      <div className="mt-14 space-y-4">
        <ArchLane n="01" title="Synchronous pre-settlement check" meta="< 100 ms p95 target" steps={path1} speed={4.8} />
        <ArchLane n="02" title="Asynchronous confirmed graph" meta="Redis Streams" steps={path2} speed={6} dim />
      </div>
    </section>
  )
}

function ArchLane({ n, title, meta, steps, speed, dim }: { n: string; title: string; meta: string; steps: string[][]; speed: number; dim?: boolean }) {
  return (
    <Reveal className={`${card} dot-grid p-6`}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="tabular font-mono text-[11px] text-white/40">PATH {n}</span>
        <span className="text-[15px] font-medium">{title}</span>
        <span className="ml-auto rounded-full border border-white/10 px-2.5 py-0.5 font-mono text-[11px] text-[#efc8a9]">{meta}</span>
      </div>
      <div className="relative mt-6 overflow-x-auto pb-1 scrollbar-thin">
        <div className="relative flex min-w-[980px] items-center">
          <div className="absolute inset-x-6 top-1/2 h-px bg-white/15" />
          <motion.span
            className="absolute top-1/2 -mt-[3px] size-[6px] rounded-full bg-[#efc8a9] shadow-[0_0_12px_#efc8a9]"
            initial={{ left: '2%' }}
            animate={{ left: ['2%', '97%'] }}
            transition={{ duration: speed, repeat: Infinity, ease: 'linear' }}
          />
          {steps.map(([t, s], i) => (
            <div key={t} className={`relative z-10 min-w-0 flex-1 ${i ? 'ml-6' : ''}`}>
              <div className={`w-full rounded-[9px] border bg-[#161412] ${i === steps.length - 1 ? 'border-[#efc8a9]/40' : 'border-white/[0.09]'}`}>
                <div className="flex items-center gap-2 border-b border-white/[0.07] px-3 py-2 text-[12.5px] font-medium">
                  <span className={`size-2 rounded-full ${dim ? 'bg-white/40' : 'bg-[#efc8a9]'}`} />
                  {t}
                </div>
                <div className="px-3 py-2 font-mono text-[10.5px] text-white/50">{s}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </Reveal>
  )
}

/* ------------------------------ Final CTA & footer ------------------------------ */
function FinalCTA() {
  return (
    <section className="mx-auto max-w-[1240px] px-6 pt-40">
      <Reveal className="relative overflow-hidden rounded-[18px] border border-white/[0.07]">
        <img src={HERO_IMG} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover object-[50%_55%] opacity-70" />
        <div className="absolute inset-0 bg-gradient-to-t from-black via-black/60 to-black/30" />
        <div className="relative flex flex-col items-center px-6 py-24 text-center">
          <LogoMark size={34} className="text-white" />
          <h2 className="mt-8 font-serif text-[clamp(36px,5vw,64px)] font-light leading-[1.04] tracking-[-0.02em]">
            Turn transaction data
            <br />
            into financial intelligence
          </h2>
          <button onClick={toConsole} className="group mt-10 inline-flex items-center gap-2 rounded-full bg-white px-6 py-3 text-[14px] font-medium text-black transition-transform duration-500 hover:scale-[1.03]">
            Launch VeriFlow <ArrowRight className="size-4 transition-transform duration-500 group-hover:translate-x-0.5" />
          </button>
        </div>
      </Reveal>
    </section>
  )
}

function Footer() {
  return (
    <footer className="mx-auto mt-24 max-w-[1240px] px-6 pb-10">
      <div className="flex flex-col gap-8 border-t border-white/[0.07] pt-10 md:flex-row md:items-start">
        <div>
          <Logo />
          <p className="mt-3 text-[13px] text-white/45">Graph-based UPI mule & collusion detection.</p>
        </div>
        <div className="flex gap-14 text-[13px] md:ml-auto">
          <div className="space-y-2.5">
            <p className="text-white/35">Product</p>
            <a href="#/console/overview" className="block text-white/75 hover:text-white">Console</a>
            <a href="#/detection" className="block text-white/75 hover:text-white">Detection</a>
          </div>
          <div className="space-y-2.5">
            <p className="text-white/35">Developers</p>
            <a href="#/architecture" className="block text-white/75 hover:text-white">Architecture</a>
            <a href="#/console/settings" className="block text-white/75 hover:text-white">API</a>
          </div>
          <div className="space-y-2.5">
            <p className="text-white/35">Source</p>
            <span className="flex items-center gap-1.5 text-white/40">
              <GitFork className="size-3.5" /> GitHub
            </span>
          </div>
        </div>
      </div>
      <div className="mt-10 flex flex-wrap justify-between gap-2 text-[12px] text-white/30">
        <span>© {new Date().getFullYear()} VeriFlow</span>
        <span>Risk intelligence only — does not settle, block, or intercept payments.</span>
      </div>
    </footer>
  )
}
