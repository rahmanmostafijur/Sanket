import { Pencil, Save, X } from 'lucide-react'
import type { FormEvent, ReactNode, RefObject } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/primitives'

interface CvBannerProps {
  count: number
  unit: 'field' | 'row'
  onDismiss: () => void
}

/** Says that the editor holds values from a CV that nothing has saved yet. */
export function CvBanner({ count, unit, onDismiss }: CvBannerProps) {
  return (
    <div role="status" className="flex items-start justify-between gap-3 rounded-xl border border-accent/30 bg-accent/[0.07] px-4 py-3 text-[13.5px] text-fg-2">
      <p>
        Filled from your CV: {count} {count === 1 ? unit : `${unit}s`}. Review them, then press Save. Nothing is saved yet.
      </p>
      <Button variant="ghost" size="sm" onClick={onDismiss}><X /> Dismiss</Button>
    </div>
  )
}

interface SectionCardProps {
  title: string
  description?: string
  editing: boolean
  onEdit: () => void
  onCancel: () => void
  onSubmit: () => void
  saving: boolean
  formRef: RefObject<HTMLFormElement | null>
  /** The summary of what is wrong, or a failure no field owns. */
  message: string | null
  banner: ReactNode
  /** The saved data, or an empty state that says what to add. */
  read: ReactNode
  editor: ReactNode
}

/** A section of the career profile: its saved data with an Edit button, or an editor with Save and Cancel. */
export function SectionCard({ title, description, editing, onEdit, onCancel, onSubmit, saving, formRef, message, banner, read, editor }: SectionCardProps) {
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!saving) onSubmit()
  }
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[16px] font-semibold text-fg">{title}</h2>
          {description ? <p className="mt-1 text-[13.5px] text-muted">{description}</p> : null}
        </div>
        {editing ? null : <Button variant="outline" size="sm" aria-label={`Edit ${title}`} onClick={onEdit}><Pencil /> Edit</Button>}
      </div>
      {editing ? (
        <form ref={formRef} onSubmit={submit} noValidate aria-label={`Edit ${title}`} className="mt-5 space-y-5">
          {banner}
          {message ? <p role="alert" className="rounded-xl border border-danger/30 bg-danger/[0.07] px-4 py-3 text-[13.5px] text-danger">{message}</p> : null}
          {editor}
          <div className="flex flex-wrap items-center gap-2.5 border-t border-line pt-4">
            <Button type="submit" variant="primary" disabled={saving}><Save /> {saving ? 'Saving...' : 'Save'}</Button>
            <Button variant="secondary" disabled={saving} onClick={onCancel}>Cancel</Button>
          </div>
        </form>
      ) : (
        <div className="mt-5">{read}</div>
      )}
    </Card>
  )
}
