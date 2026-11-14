import { motion } from 'motion/react'
import { blurIn } from '../../ui/Reveal'

export function PageHead({ title, sub, right }: { title: string; sub: string; right?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <motion.div variants={blurIn}>
        <h1 className="text-[22px] font-medium tracking-[-0.015em] text-ink">{title}</h1>
        <p className="mt-1 text-[13px] text-muted">{sub}</p>
      </motion.div>
      {right && (
        <motion.div variants={blurIn} className="flex flex-wrap items-center gap-2">
          {right}
        </motion.div>
      )}
    </div>
  )
}

export function Chip({ active, onClick, children }: { active: boolean; onClick(): void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex h-7 items-center gap-1.5 rounded-[8px] border px-2.5 text-[12px] transition-colors duration-200 ${
        active ? 'border-primary bg-primary text-primary-fg' : 'border-line-strong bg-surface text-ink-2 hover:bg-hover'
      }`}
    >
      {children}
    </button>
  )
}

export function PrimaryButton({ onClick, children }: { onClick(): void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className="inline-flex h-9 items-center gap-1.5 rounded-[9px] bg-primary px-3.5 text-[13px] font-medium text-primary-fg shadow-[0_1px_2px_rgba(0,0,0,0.2)] transition-[opacity,transform] duration-200 hover:opacity-90 active:scale-[0.98]">
      {children}
    </button>
  )
}
export function GhostButton({ onClick, children }: { onClick(): void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className="inline-flex h-9 items-center gap-1.5 rounded-[9px] border border-line-strong bg-surface px-3 text-[13px] text-ink-2 transition-colors hover:bg-hover">
      {children}
    </button>
  )
}

export function SearchInput({ value, onChange, placeholder }: { value: string; onChange(v: string): void; placeholder: string }) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      aria-label={placeholder}
      className="h-8 w-[220px] rounded-[8px] border border-line-strong bg-surface px-3 text-[12.5px] text-ink outline-none placeholder:text-faint focus:border-muted"
    />
  )
}

export function Pager({ page, pages, onPage, total }: { page: number; pages: number; onPage(p: number): void; total: number }) {
  return (
    <div className="flex items-center justify-between px-4 py-3 text-[12px] text-muted">
      <span className="tabular">{total.toLocaleString('en-IN')} results</span>
      <span className="flex items-center gap-1.5">
        <button disabled={page <= 0} onClick={() => onPage(page - 1)} className="h-7 rounded-[7px] border border-line-strong px-2.5 text-ink-2 transition-colors hover:bg-hover disabled:opacity-40">
          Prev
        </button>
        <span className="tabular px-1.5">
          {pages ? page + 1 : 0} / {pages}
        </span>
        <button disabled={page >= pages - 1} onClick={() => onPage(page + 1)} className="h-7 rounded-[7px] border border-line-strong px-2.5 text-ink-2 transition-colors hover:bg-hover disabled:opacity-40">
          Next
        </button>
      </span>
    </div>
  )
}
