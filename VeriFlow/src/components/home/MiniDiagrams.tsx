import type { ReactNode } from 'react'

const PEACH = '#efc8a9'
const LINE = '#3a3632'

function Node({ x, y, r = 5, hot }: { x: number; y: number; r?: number; hot?: boolean }) {
  return (
    <g>
      {hot && (
        <circle cx={x} cy={y} r={r} fill={PEACH} opacity="0.4">
          <animate attributeName="r" values={`${r};${r * 2.4}`} dur="2.2s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.4;0" dur="2.2s" repeatCount="indefinite" />
        </circle>
      )}
      <circle cx={x} cy={y} r={r} fill={hot ? PEACH : '#1c1a18'} stroke={hot ? PEACH : '#4a4540'} strokeWidth="1" />
    </g>
  )
}

function Flow({ d, dur = 1.8, begin = 0 }: { d: string; dur?: number; begin?: number }) {
  return (
    <>
      <path d={d} fill="none" stroke={LINE} strokeWidth="1" />
      <circle r="1.8" fill={PEACH}>
        <animateMotion path={d} dur={`${dur}s`} begin={`${begin}s`} repeatCount="indefinite" />
        <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.85;1" dur={`${dur}s`} begin={`${begin}s`} repeatCount="indefinite" />
      </circle>
    </>
  )
}

function Frame({ children, label }: { children: ReactNode; label: string }) {
  return (
    <svg viewBox="0 0 200 110" className="h-full w-full" role="img" aria-label={label}>
      {children}
    </svg>
  )
}

export function FanOutDiagram() {
  const ys = [16, 36, 56, 76, 96]
  return (
    <Frame label="One account distributing funds to many receivers">
      {ys.map((y, i) => (
        <Flow key={y} d={`M 50 56 C 100 56 110 ${y} 150 ${y}`} begin={i * 0.25} />
      ))}
      {ys.map((y) => (
        <Node key={y} x={152} y={y} r={4} />
      ))}
      <Node x={48} y={56} r={7} hot />
    </Frame>
  )
}

export function FanInDiagram() {
  const ys = [16, 36, 56, 76, 96]
  return (
    <Frame label="Many senders converging on one account">
      {ys.map((y, i) => (
        <Flow key={y} d={`M 50 ${y} C 90 ${y} 100 56 150 56`} begin={i * 0.25} />
      ))}
      {ys.map((y) => (
        <Node key={y} x={48} y={y} r={4} />
      ))}
      <Node x={152} y={56} r={7} hot />
    </Frame>
  )
}

export function PassThroughDiagram() {
  return (
    <Frame label="Funds received and forwarded rapidly">
      <Flow d="M 30 56 L 100 56" dur={1.4} />
      <Flow d="M 100 56 L 170 56" dur={1.4} begin={0.7} />
      <Node x={30} y={56} r={5} />
      <Node x={100} y={56} r={7} hot />
      <Node x={170} y={56} r={5} />
      <text x="65" y="46" fontSize="8" fill="#9a938d" textAnchor="middle" className="tabular">
        ₹25,000
      </text>
      <text x="135" y="46" fontSize="8" fill={PEACH} textAnchor="middle" className="tabular">
        ₹24,500
      </text>
      <text x="100" y="82" fontSize="7.5" fill="#6d6762" textAnchor="middle" fontFamily="JetBrains Mono, monospace">
        ratio 0.98
      </text>
    </Frame>
  )
}

export function CycleDiagram() {
  const d = 'M 100 18 C 140 18 150 40 150 55 C 150 80 130 94 100 94 C 70 94 50 80 50 55 C 50 34 66 18 100 18'
  return (
    <Frame label="Money looping back to its origin">
      <path d={d} fill="none" stroke={LINE} />
      {[0, 0.9, 1.8].map((b) => (
        <circle key={b} r="1.8" fill={PEACH}>
          <animateMotion path={d} dur="2.7s" begin={`${b}s`} repeatCount="indefinite" />
        </circle>
      ))}
      <Node x={100} y={18} r={6} hot />
      <Node x={150} y={55} r={4.5} />
      <Node x={100} y={94} r={4.5} />
      <Node x={50} y={55} r={4.5} />
    </Frame>
  )
}

export function MultiHopDiagram() {
  const pts = [
    [20, 80],
    [60, 40],
    [100, 72],
    [140, 32],
    [180, 62],
  ]
  return (
    <Frame label="Layered path through intermediary accounts">
      {pts.slice(1).map((p, i) => (
        <Flow key={i} d={`M ${pts[i][0]} ${pts[i][1]} L ${p[0]} ${p[1]}`} dur={0.9} begin={i * 0.45} />
      ))}
      {pts.map(([x, y], i) => (
        <Node key={i} x={x} y={y} r={i === 0 || i === 4 ? 6 : 4.5} hot={i === 0 || i === 4} />
      ))}
      {[1, 2, 3, 4].map((h, i) => (
        <text key={h} x={(pts[i][0] + pts[i + 1][0]) / 2} y={(pts[i][1] + pts[i + 1][1]) / 2 + 14} fontSize="7" fill="#6d6762" textAnchor="middle">
          {h}
        </text>
      ))}
    </Frame>
  )
}
