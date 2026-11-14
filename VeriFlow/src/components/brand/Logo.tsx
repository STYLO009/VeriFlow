/** Placeholder VeriFlow mark — swap the SVG when the final logo is supplied. */
export function LogoMark({ size = 22, className = '' }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={`block shrink-0 ${className}`} aria-hidden>
      <circle cx="12" cy="12" r="12" fill="currentColor" />
      <path d="M6.6 7.4 L12 16.8 L17.4 7.4" fill="none" stroke="var(--logo-ink, #0d0c0b)" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="6.6" cy="7.4" r="1.55" fill="var(--logo-ink, #0d0c0b)" />
      <circle cx="17.4" cy="7.4" r="1.55" fill="var(--logo-ink, #0d0c0b)" />
    </svg>
  )
}

export function Logo({ className = '', tone = 'light' }: { className?: string; tone?: 'light' | 'ink' }) {
  return (
    <span className={`flex items-center gap-2 ${className}`}>
      <LogoMark className={tone === 'light' ? 'text-white' : 'text-ink'} />
      <span className={`text-[15px] font-semibold leading-none tracking-[-0.01em] ${tone === 'light' ? 'text-white' : 'text-ink'}`}>VeriFlow</span>
    </span>
  )
}
