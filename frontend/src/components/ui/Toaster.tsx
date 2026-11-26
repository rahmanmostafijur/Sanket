import { Zap } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router'
import { toast as sonnerToast } from 'sonner'
import { Toaster as SonnerToaster } from '@/components/ui/sonner'
import { useToasts, type Toast } from '@/stores/toasts'

const DISMISS_AFTER_MS = 5500
const MAX_VISIBLE = 4

/**
 * Renders the toast store through Sonner. The store stays the single entry point (`toast()`),
 * so callers do not change; each new entry is shown once and removed from Sonner when the store
 * drops it (for example `dismissTone`).
 */
export function Toaster() {
  const toasts = useToasts((s) => s.toasts)
  const dismiss = useToasts((s) => s.dismiss)
  const navigate = useNavigate()
  const shown = useRef(new Set<number>())

  useEffect(() => {
    const live = new Set(toasts.map((t) => t.id))
    for (const id of shown.current) {
      if (!live.has(id)) {
        sonnerToast.dismiss(id)
        shown.current.delete(id)
      }
    }
    for (const entry of toasts) {
      if (shown.current.has(entry.id)) continue
      shown.current.add(entry.id)
      show(entry, navigate, () => dismiss(entry.id))
    }
  }, [toasts, dismiss, navigate])

  return <SonnerToaster position="bottom-right" visibleToasts={MAX_VISIBLE} closeButton />
}

function show(entry: Toast, navigate: (to: string) => void | Promise<void>, onGone: () => void): void {
  const action = entry.action
  const options = {
    id: entry.id,
    description: entry.description,
    duration: DISMISS_AFTER_MS,
    onDismiss: onGone,
    onAutoClose: onGone,
    action: action
      ? {
          label: `${action.label} →`,
          onClick: () => {
            void navigate(action.href)
          },
        }
      : undefined,
  }
  if (entry.tone === 'success') sonnerToast.success(entry.title, options)
  else if (entry.tone === 'error') sonnerToast.error(entry.title, options)
  else if (entry.tone === 'match') {
    sonnerToast(entry.title, { ...options, icon: <Zap className="size-4 text-accent" />, className: 'border-accent/30' })
  } else sonnerToast.info(entry.title, options)
}
