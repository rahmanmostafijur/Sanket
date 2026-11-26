import { Check, ChevronDown } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
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
    <DropdownMenu open={open} onOpenChange={setOpen} modal={false}>
      <DropdownMenuTrigger asChild>
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
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align={align}
        sideOffset={6}
        className="w-auto min-w-[200px] rounded-xl border border-line-strong bg-popover p-1.5 shadow-[var(--shadow-pop)] ring-0"
      >
        <DropdownMenuLabel className="px-2.5 pb-1.5 pt-1 text-[11px] font-semibold uppercase tracking-wider text-subtle">
          {label}
        </DropdownMenuLabel>
        {options.map((option) => {
          const chosen = isChosen(props, option.value)
          return (
            <DropdownMenuItem
              key={String(option.value)}
              onSelect={(event) => {
                if (props.multiple) event.preventDefault()
                choose(option.value)
              }}
              className="cursor-pointer gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] text-fg-2"
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
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
