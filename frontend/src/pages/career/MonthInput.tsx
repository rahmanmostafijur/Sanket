import { Input } from '@/components/ui/Field'

interface MonthInputProps {
  id: string
  /** "YYYY-MM", or null / "" for no month. */
  value: string | null
  onChange: (value: string) => void
  invalid: boolean
  disabled?: boolean
}

/** A month picker. Where the browser has none it is a text box, and the placeholder shows the format. */
export function MonthInput({ id, value, onChange, invalid, disabled }: MonthInputProps) {
  return <Input id={id} type="month" value={value ?? ''} placeholder="YYYY-MM" disabled={disabled} aria-invalid={invalid} onChange={(event) => onChange(event.target.value)} />
}
