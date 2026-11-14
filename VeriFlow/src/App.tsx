import { lazy, Suspense, useEffect } from 'react'
import { AnimatePresence, motion, MotionConfig } from 'motion/react'
import { useRoute } from './lib/router'
import HomePage from './components/home/HomePage'
import { EASE } from './components/ui/Reveal'

const DashboardPage = lazy(() => import('./components/dashboard/DashboardPage'))

export default function App() {
  const route = useRoute()

  useEffect(() => {
    document.title = route.page === 'console' ? 'VeriFlow Console' : 'VeriFlow — Graph Intelligence for UPI Risk'
    if (route.page === 'home' && route.anchor) {
      requestAnimationFrame(() => document.getElementById(route.anchor!)?.scrollIntoView({ behavior: 'smooth' }))
    } else window.scrollTo({ top: 0 })
  }, [route.page, route.page === 'home' ? route.anchor : null])

  // Warm the console chunk while the visitor reads the homepage.
  useEffect(() => {
    const id = setTimeout(() => import('./components/dashboard/DashboardPage'), 1800)
    return () => clearTimeout(id)
  }, [])

  return (
    <MotionConfig reducedMotion="user">
      <AnimatePresence mode="wait" initial={false}>
        {route.page === 'home' ? (
          <motion.div
            key="home"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1, transition: { duration: 0.5, ease: EASE } }}
            exit={{ opacity: 0, filter: 'blur(6px)', transition: { duration: 0.35, ease: EASE } }}
          >
            <HomePage />
          </motion.div>
        ) : (
          <motion.div key="console" initial={{ opacity: 0 }} animate={{ opacity: 1, transition: { duration: 0.4 } }} exit={{ opacity: 0, transition: { duration: 0.25 } }}>
            <Suspense fallback={<div className="h-dvh bg-[#f3f3f3]" />}>
              <DashboardPage view={route.view} />
            </Suspense>
          </motion.div>
        )}
      </AnimatePresence>
    </MotionConfig>
  )
}
