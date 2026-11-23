import { CircleCheck, CircleX, Info, X, Zap } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect } from 'react'
import { Link } from 'react-router'
import { cn } from '@/lib/cn'
import { useToasts, type Toast } from '@/stores/toasts'

const DISMISS_AFTER_MS = 5500

const ICONS = {
  default: <Info className="size-4 text-info" />,
  success: <CircleCheck className="size-4 text-accent" />,
  error: <CircleX className="size-4 text-danger" />,
  match: <Zap className="size-4 text-accent" />,
} as const

function ToastCard({ toast }: { toast: Toast }) {
  const dismiss = useToasts((s) => s.dismiss)
  useEffect(() => {
    const timer = setTimeout(() => dismiss(toast.id), DISMISS_AFTER_MS)
    return () => clearTimeout(timer)
  }, [toast.id, dismiss])
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 16, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 40, transition: { duration: 0.18 } }}
      transition={{ type: 'spring', stiffness: 420, damping: 32 }}
      role="status"
      className={cn(
        'pointer-events-auto flex w-[340px] max-w-[calc(100vw-32px)] items-start gap-3 rounded-xl border bg-[#121b27]/95 p-3.5 shadow-[var(--shadow-pop)] backdrop-blur',
        toast.tone === 'match' ? 'border-accent/30' : 'border-line-strong',
      )}
    >
      <span className="mt-0.5">{ICONS[toast.tone]}</span>
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] font-semibold text-fg">{toast.title}</p>
        {toast.description ? <p className="mt-0.5 truncate text-[13px] text-muted">{toast.description}</p> : null}
        {toast.action ? (
          <Link
            to={toast.action.href}
            onClick={() => dismiss(toast.id)}
            className="mt-2 inline-flex text-[13px] font-medium text-accent hover:underline"
          >
            {toast.action.label} →
          </Link>
        ) : null}
      </div>
      <button type="button" aria-label="Dismiss" onClick={() => dismiss(toast.id)} className="text-subtle hover:text-fg">
        <X className="size-4" />
      </button>
    </motion.div>
  )
}

export function Toaster() {
  const toasts = useToasts((s) => s.toasts)
  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col items-end gap-2">
      <AnimatePresence initial={false}>
        {toasts.map((toast) => (
          <ToastCard key={toast.id} toast={toast} />
        ))}
      </AnimatePresence>
    </div>
  )
}
