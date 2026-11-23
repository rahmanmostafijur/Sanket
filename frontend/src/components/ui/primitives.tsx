import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-[var(--radius-card)] border border-line bg-surface shadow-[var(--shadow-card)]', className)}
      {...props}
    />
  )
}

interface CardHeaderProps {
  title: ReactNode
  icon?: ReactNode
  action?: ReactNode
  className?: string
}

export function CardHeader({ title, icon, action, className }: CardHeaderProps) {
  return (
    <div className={cn('flex items-center justify-between gap-3', className)}>
      <h2 className="flex items-center gap-2.5 text-[15px] font-semibold tracking-[-0.01em] text-fg">
        {icon}
        {title}
      </h2>
      {action}
    </div>
  )
}

export function Chip({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center rounded-md bg-[#18222f] px-2.5 text-xs font-medium text-fg-2 ring-1 ring-inset ring-white/[0.03]',
        className,
      )}
      {...props}
    />
  )
}

export function Kbd({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn(
        'inline-flex h-6 min-w-6 items-center justify-center gap-0.5 rounded-md border border-line-strong bg-elevated px-1.5 font-sans text-[11px] font-medium text-muted',
        className,
      )}
      {...props}
    />
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('skeleton rounded-md', className)} />
}

/** Small pulsing status dot. */
export function StatusDot({ tone = 'accent', pulse = false, className }: { tone?: 'accent' | 'amber' | 'danger' | 'muted' | 'info'; pulse?: boolean; className?: string }) {
  const color = {
    accent: 'bg-accent',
    amber: 'bg-amber',
    danger: 'bg-danger',
    muted: 'bg-subtle',
    info: 'bg-info',
  }[tone]
  return <span aria-hidden className={cn('inline-block size-2 shrink-0 rounded-full', color, pulse && 'animate-pulse-dot', className)} />
}

export function SectionLabel({ className, ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn('text-[13px] font-medium text-fg-2', className)} {...props} />
}

/** Pill that marks content as demo data, so it is never mistaken for real data. */
export function DemoTag({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-5 items-center rounded-full border border-amber/35 bg-amber/10 px-2 text-[10.5px] font-semibold uppercase tracking-wide text-amber',
        className,
      )}
    >
      Demo data
    </span>
  )
}
