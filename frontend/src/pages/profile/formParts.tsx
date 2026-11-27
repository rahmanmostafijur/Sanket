import type { ReactNode } from 'react'
import { Card } from '@/components/ui/primitives'
import { cn } from '@/lib/cn'

export function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Card className="p-5 sm:p-6">
      <h2 className="text-[16px] font-semibold text-fg">{title}</h2>
      {description ? <p className="mt-1 text-[13.5px] text-muted">{description}</p> : null}
      <div className="mt-5 space-y-5">{children}</div>
    </Card>
  )
}

/**
 * Marks a field whose value came from somewhere other than the user, such as a CV. The wrapper
 * always renders and only its classes change, so the input inside keeps focus when the mark goes
 * away on the first edit.
 */
export function Filled({ on, label = 'Filled from CV', children }: { on: boolean; label?: string; children: ReactNode }) {
  return (
    <div className={cn('relative rounded-lg', on && 'outline outline-1 outline-offset-4 outline-accent/45')}>
      {on ? <span className="absolute right-0 top-0 text-[11px] font-medium text-accent">{label}</span> : null}
      {children}
    </div>
  )
}
