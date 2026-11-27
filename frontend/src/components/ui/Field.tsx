import { X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { Switch as SwitchPrimitive } from 'radix-ui'
import { forwardRef, useId, useState, type InputHTMLAttributes, type KeyboardEvent, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

const CONTROL =
  'w-full rounded-[10px] border border-line-strong bg-bg/60 px-3.5 text-[14px] text-fg outline-none transition-[border-color,box-shadow] placeholder:text-subtle hover:border-[#34445b] focus:border-accent/45 focus:shadow-[0_0_0_3px_rgb(184_243_107/0.08)] disabled:opacity-50 aria-[invalid=true]:border-danger/60'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...props }, ref) {
  return <input ref={ref} className={cn(CONTROL, 'h-10', className)} {...props} />
})

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={cn(CONTROL, 'min-h-[110px] resize-y py-2.5 leading-relaxed', className)} {...props} />
})

/** A native select, which stays usable with a keyboard and on a phone. */
export const NativeSelect = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function NativeSelect({ className, ...props }, ref) {
  return <select ref={ref} className={cn(CONTROL, 'h-10', className)} {...props} />
})

interface FieldProps {
  label: string
  hint?: ReactNode
  error?: string | null
  htmlFor?: string
  /** Names the field for code that has to find it, such as focusing the first invalid one. */
  fieldKey?: string
  children: ReactNode
  className?: string
}

export function Field({ label, hint, error, htmlFor, fieldKey, children, className }: FieldProps) {
  return (
    <div data-field={fieldKey} className={cn('space-y-2', className)}>
      <label htmlFor={htmlFor} className="block text-[13.5px] font-medium text-fg">{label}</label>
      {children}
      {error ? <p role="alert" className="text-[12.5px] text-danger">{error}</p> : hint ? <p className="text-[12.5px] leading-relaxed text-subtle">{hint}</p> : null}
    </div>
  )
}

interface SwitchProps {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  label: string
  description?: ReactNode
  disabled?: boolean
}

export function SwitchRow({ checked, onCheckedChange, label, description, disabled }: SwitchProps) {
  const id = useId()
  return (
    <div className="flex items-start justify-between gap-6 py-3.5">
      <label htmlFor={id} className="min-w-0 cursor-pointer">
        <span className="block text-[14px] font-medium text-fg">{label}</span>
        {description ? <span className="mt-0.5 block text-[13px] leading-relaxed text-muted">{description}</span> : null}
      </label>
      <SwitchPrimitive.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        className="relative mt-0.5 h-6 w-11 shrink-0 rounded-full border border-line-strong bg-elevated transition-colors data-[state=checked]:border-accent/60 data-[state=checked]:bg-accent disabled:opacity-50"
      >
        <SwitchPrimitive.Thumb className="block size-[18px] translate-x-[2px] rounded-full bg-fg-2 shadow transition-transform duration-200 data-[state=checked]:translate-x-[22px] data-[state=checked]:bg-accent-ink" />
      </SwitchPrimitive.Root>
    </div>
  )
}

interface TagInputProps {
  id?: string
  value: readonly string[]
  onChange: (value: string[]) => void
  placeholder?: string
  max?: number
  maxLength?: number
  /** Normalise each entry (e.g. upper-case country codes); return null to reject it. */
  normalize?: (raw: string) => string | null
  tone?: 'accent' | 'info' | 'default'
}

/** Type and press Enter or comma to add; Backspace on an empty field removes the last tag. */
export function TagInput({ id, value, onChange, placeholder, max = 20, maxLength = 60, normalize, tone = 'default' }: TagInputProps) {
  const [draft, setDraft] = useState('')
  const [rejected, setRejected] = useState(false)
  const full = value.length >= max
  const add = (raw: string) => {
    const trimmed = raw.trim()
    if (!trimmed) return
    const next = normalize ? normalize(trimmed) : trimmed.slice(0, maxLength)
    if (next === null) {
      setRejected(true)
      return
    }
    if (!value.some((item) => item.toLowerCase() === next.toLowerCase()) && !full) onChange([...value, next])
    setDraft('')
    setRejected(false)
  }
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault()
      add(draft)
    } else if (event.key === 'Backspace' && !draft && value.length) {
      onChange(value.slice(0, -1))
    }
  }
  const tagStyle = {
    accent: 'border-accent/30 bg-accent/10 text-accent',
    info: 'border-info/30 bg-info/10 text-info',
    default: 'border-line-strong bg-elevated text-fg-2',
  }[tone]
  return (
    <div className={cn('flex min-h-10 flex-wrap items-center gap-1.5 rounded-[10px] border bg-bg/60 px-2 py-1.5 transition-colors focus-within:border-accent/45', rejected ? 'border-danger/60' : 'border-line-strong')}>
      <AnimatePresence initial={false}>
        {value.map((item) => (
          <motion.span
            key={item}
            layout
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.85 }}
            className={cn('inline-flex h-7 items-center gap-1 rounded-md border pl-2.5 pr-1 text-[13px] font-medium', tagStyle)}
          >
            {item}
            <button type="button" aria-label={`Remove ${item}`} onClick={() => onChange(value.filter((v) => v !== item))} className="grid size-5 place-items-center rounded opacity-70 hover:bg-white/10 hover:opacity-100">
              <X className="size-3" />
            </button>
          </motion.span>
        ))}
      </AnimatePresence>
      <input
        id={id}
        value={draft}
        disabled={full}
        onChange={(event) => {
          setDraft(event.target.value)
          setRejected(false)
        }}
        onKeyDown={onKeyDown}
        onBlur={() => add(draft)}
        placeholder={full ? `Up to ${max}` : value.length ? '' : placeholder}
        className="h-7 min-w-[120px] flex-1 bg-transparent px-1.5 text-[14px] text-fg outline-none placeholder:text-subtle"
      />
    </div>
  )
}

interface ToggleChipsProps<T extends string> {
  options: readonly { value: T; label: string }[]
  value: readonly T[]
  onChange: (value: T[]) => void
  label: string
}

export function ToggleChips<T extends string>({ options, value, onChange, label }: ToggleChipsProps<T>) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((option) => {
        const on = value.includes(option.value)
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter((v) => v !== option.value) : [...value, option.value])}
            className={cn(
              'h-9 rounded-[10px] border px-3.5 text-[13.5px] font-medium transition-colors',
              on ? 'border-accent/50 bg-accent/10 text-accent' : 'border-line-strong text-fg-2 hover:border-[#34445b] hover:text-fg',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
