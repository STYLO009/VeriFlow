import { useEffect } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import { EASE } from '../ui/Reveal'

/** Right-side drawer — reference motion: page dims, panel slides + un-blurs. */
export default function Drawer({ open, onClose, title, icon, children, width = 440 }: { open: boolean; onClose(): void; title: React.ReactNode; icon?: React.ReactNode; children: React.ReactNode; width?: number }) {
  useEffect(() => {
    if (!open) return
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [open, onClose])
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="scrim"
            className="fixed inset-0 z-40 bg-[color-mix(in_srgb,var(--ink)_10%,transparent)]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.35, ease: EASE }}
            onClick={onClose}
          />
          <motion.aside
            key="panel"
            role="dialog"
            aria-modal="true"
            className="fixed bottom-3 right-3 top-3 z-50 flex max-w-[calc(100vw-24px)] flex-col overflow-hidden rounded-[14px] border border-line bg-surface shadow-pop"
            style={{ width }}
            initial={{ x: 40, opacity: 0, filter: 'blur(8px)' }}
            animate={{ x: 0, opacity: 1, filter: 'blur(0px)' }}
            exit={{ x: 40, opacity: 0, filter: 'blur(6px)' }}
            transition={{ duration: 0.5, ease: EASE }}
          >
            <div className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-4">
              {icon}
              <span className="text-[13.5px] font-medium text-ink">{title}</span>
              <button onClick={onClose} aria-label="Close panel" className="ml-auto grid size-6 place-items-center rounded-[6px] border border-line-strong text-muted transition-colors hover:text-ink">
                <X className="size-3.5" />
              </button>
            </div>
            <div className="scrollbar-thin flex-1 overflow-y-auto">{children}</div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
