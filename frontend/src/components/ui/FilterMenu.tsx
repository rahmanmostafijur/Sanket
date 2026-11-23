import { Check, ChevronDown } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { DropdownMenu } from 'radix-ui'
import { useState, type ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface MenuOption<T extends string | number> {
  value: T
  label: string
  hint?: ReactNode
}

interface BaseProps<T extends string | number> {
  label: string
  options: readonly MenuOption<T>[]
  /** Text shown on the chip when something is chosen. */
  summary?: string
  align?: 'start' | 'end'
  /** Highlight the chip as an applied filter (multi-selects work this out themselves). */
  active?: boolean
  className?: string
}

interface MultiProps<T extends string | number> extends BaseProps<T> {
  multiple: true
  value: readonly T[]
  onChange: (value: T[]) => void
}

interface SingleProps<T extends string | number> extends BaseProps<T> {
  multiple?: false
  value: T
  onChange: (value: T) => void
}

export type FilterMenuProps<T extends string | number> = MultiProps<T> | SingleProps<T>

const MENU_MOTION = {
  initial: { opacity: 0, y: -4, scale: 0.98 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -4, scale: 0.98 },
  transition: { duration: 0.14, ease: [0.22, 1, 0.36, 1] },
} as const

function isChosen<T extends string | number>(props: FilterMenuProps<T>, value: T): boolean {
  return props.multiple ? props.value.includes(value) : props.value === value
}

/** Chip-style dropdown, single or multi select (the filter row of the dashboard and Discover). */
export function FilterMenu<T extends string | number>(props: FilterMenuProps<T>) {
  const [open, setOpen] = useState(false)
  const { label, options, summary, align = 'start', className } = props
  const active = props.active ?? (props.multiple ? props.value.length > 0 : false)

  const choose = (value: T) => {
    if (props.multiple) {
      const next = props.value.includes(value) ? props.value.filter((v) => v !== value) : [...props.value, value]
      props.onChange(next)
    } else {
      props.onChange(value)
    }
  }

  return (
    <DropdownMenu.Root open={open} onOpenChange={setOpen} modal={false}>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className={cn(
            'inline-flex h-9 items-center gap-2 rounded-[10px] border bg-surface px-3.5 text-[13.5px] font-medium transition-colors',
            active ? 'border-accent/45 text-fg' : 'border-line-strong text-fg-2 hover:border-[#34445b] hover:text-fg',
            open && 'border-[#3a4b63] bg-elevated',
            className,
          )}
        >
          <span className="truncate">{summary ?? label}</span>
          {props.multiple && props.value.length > 1 ? (
            <span className="rounded bg-accent/15 px-1.5 text-[11px] font-semibold text-accent tabular">{props.value.length}</span>
          ) : null}
          <ChevronDown className={cn('size-3.5 text-muted transition-transform', open && 'rotate-180')} />
        </button>
      </DropdownMenu.Trigger>
      <AnimatePresence>
        {open ? (
          <DropdownMenu.Portal forceMount>
            <DropdownMenu.Content asChild align={align} sideOffset={6} forceMount>
              <motion.div
                {...MENU_MOTION}
                className="z-50 min-w-[200px] rounded-xl border border-line-strong bg-[#121b27] p-1.5 shadow-[var(--shadow-pop)]"
              >
                <DropdownMenu.Label className="px-2.5 pb-1.5 pt-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">
                  {label}
                </DropdownMenu.Label>
                {options.map((option) => {
                  const chosen = isChosen(props, option.value)
                  return (
                    <DropdownMenu.Item
                      key={String(option.value)}
                      onSelect={(event) => {
                        if (props.multiple) event.preventDefault()
                        choose(option.value)
                      }}
                      className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] text-fg-2 outline-none data-[highlighted]:bg-elevated data-[highlighted]:text-fg"
                    >
                      <span
                        className={cn(
                          'grid size-4 place-items-center rounded border',
                          chosen ? 'border-accent bg-accent text-accent-ink' : 'border-line-strong',
                          !props.multiple && 'rounded-full',
                        )}
                      >
                        {chosen ? <Check className="size-3" strokeWidth={3} /> : null}
                      </span>
                      <span className="flex-1">{option.label}</span>
                      {option.hint ? <span className="text-xs text-subtle">{option.hint}</span> : null}
                    </DropdownMenu.Item>
                  )
                })}
              </motion.div>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        ) : null}
      </AnimatePresence>
    </DropdownMenu.Root>
  )
}
