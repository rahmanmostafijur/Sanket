import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface TabItem<T extends string> {
  value: T
  label: ReactNode
  count?: number
  icon?: ReactNode
}

interface TabsProps<T extends string> {
  items: readonly TabItem<T>[]
  value: T
  onChange: (value: T) => void
  /** Unique per tab group on a page, so the moving underline animates within its own group. */
  id: string
  className?: string
}

/** Underlined tabs with a lime indicator that slides between items. */
export function UnderlineTabs<T extends string>({ items, value, onChange, id, className }: TabsProps<T>) {
  return (
    <div role="tablist" className={cn('flex items-end gap-7 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden', className)}>
      {items.map((item) => {
        const selected = item.value === value
        return (
          <button
            key={item.value}
            role="tab"
            type="button"
            aria-selected={selected}
            onClick={() => onChange(item.value)}
            className={cn(
              'relative flex shrink-0 items-center gap-2 pb-3 text-[14.5px] font-medium transition-colors',
              selected ? 'text-accent' : 'text-muted hover:text-fg-2',
            )}
          >
            {item.icon}
            {item.label}
            {item.count !== undefined ? <span className="tabular">({item.count.toLocaleString()})</span> : null}
            {selected ? (
              <motion.span
                layoutId={`tab-underline-${id}`}
                className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent shadow-[0_0_12px_rgb(184_243_107/0.6)]"
                transition={{ type: 'spring', stiffness: 500, damping: 40 }}
              />
            ) : null}
          </button>
        )
      })}
    </div>
  )
}

/** Compact segmented control (list/grid, keyword/semantic). */
export function Segmented<T extends string>({ items, value, onChange, id, className }: TabsProps<T>) {
  return (
    <div role="tablist" className={cn('inline-flex items-center gap-1 rounded-[10px] border border-line bg-surface p-1', className)}>
      {items.map((item) => {
        const selected = item.value === value
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(item.value)}
            className={cn(
              'relative flex h-8 items-center gap-1.5 rounded-[7px] px-3 text-[13px] font-medium transition-colors [&_svg]:size-4',
              selected ? 'text-accent' : 'text-muted hover:text-fg',
            )}
          >
            {selected ? (
              <motion.span
                layoutId={`segment-${id}`}
                className="absolute inset-0 rounded-[7px] bg-elevated ring-1 ring-line-strong"
                transition={{ type: 'spring', stiffness: 500, damping: 40 }}
              />
            ) : null}
            <span className="relative flex items-center gap-1.5">
              {item.icon}
              {item.label}
            </span>
          </button>
        )
      })}
    </div>
  )
}
