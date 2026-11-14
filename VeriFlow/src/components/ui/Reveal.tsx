import { motion, type HTMLMotionProps } from 'motion/react'

/** Reference motion: blur-to-sharp fade with a short rise, ease-out-quint. */
export const EASE = [0.22, 1, 0.36, 1] as const

export const blurIn = {
  hidden: { opacity: 0, filter: 'blur(8px)', y: 8 },
  show: { opacity: 1, filter: 'blur(0px)', y: 0, transition: { duration: 0.7, ease: EASE } },
}

export const stagger = (s = 0.06, delay = 0) => ({
  hidden: {},
  show: { transition: { staggerChildren: s, delayChildren: delay } },
})

export function Reveal({ delay = 0, className, children, ...rest }: HTMLMotionProps<'div'> & { delay?: number }) {
  return (
    <motion.div
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: '-60px' }}
      variants={{ hidden: blurIn.hidden, show: { ...blurIn.show, transition: { ...blurIn.show.transition, delay } } }}
      className={className}
      {...rest}
    >
      {children}
    </motion.div>
  )
}
