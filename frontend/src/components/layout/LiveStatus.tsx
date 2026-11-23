import { StatusDot } from '@/components/ui/primitives'
import { useLiveStatus } from '@/hooks/useLiveStatus'
import { cn } from '@/lib/cn'

export function LiveStatusPill({ className }: { className?: string }) {
  const view = useLiveStatus()
  const color = { accent: 'text-fg', amber: 'text-amber', danger: 'text-danger', muted: 'text-muted' }[view.tone]
  return (
    <span title={view.description} className={cn('inline-flex items-center gap-2 text-[14.5px] font-medium', color, className)}>
      <StatusDot tone={view.tone} pulse={view.pulse} />
      {view.label}
    </span>
  )
}
