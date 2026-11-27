import { BriefcaseBusiness } from 'lucide-react'
import type { Experience, ExperienceInput } from '@/api/types'
import { Field, Input, SwitchRow, Textarea } from '@/components/ui/Field'
import { EXPERIENCE } from './drafts'
import { ListSection, type RowEditorProps } from './ListSection'
import { TEXT_LIMITS } from './limits'
import { formatRange } from './months'
import { MonthInput } from './MonthInput'

const LIMITS = TEXT_LIMITS.experience

function ExperienceRead({ item }: { item: ExperienceInput }) {
  return (
    <div className="flex items-start gap-3">
      <BriefcaseBusiness className="mt-0.5 size-4 shrink-0 text-muted" />
      <div className="min-w-0">
        <p className="text-[14.5px] font-medium text-fg">{item.title}</p>
        <p className="text-[13.5px] text-fg-2">{item.company}</p>
        <p className="text-[13px] text-muted">{formatRange(item.start, item.end, item.current)}</p>
        {item.description ? <p className="mt-2 whitespace-pre-line text-[13.5px] leading-relaxed text-fg-2">{item.description}</p> : null}
      </div>
    </div>
  )
}

function ExperienceRow({ row, index, errors, idBase, onChange }: RowEditorProps<'experience'>) {
  const bad = (field: string) => Boolean(errors[field])
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Company" htmlFor={`${idBase}-company`} fieldKey={`${index}.company`} error={errors.company}>
          <Input id={`${idBase}-company`} value={row.company} maxLength={LIMITS.company} aria-invalid={bad('company')} onChange={(e) => onChange({ company: e.target.value })} placeholder="Example Ltd" />
        </Field>
        <Field label="Job title" htmlFor={`${idBase}-title`} fieldKey={`${index}.title`} error={errors.title}>
          <Input id={`${idBase}-title`} value={row.title} maxLength={LIMITS.title} aria-invalid={bad('title')} onChange={(e) => onChange({ title: e.target.value })} placeholder="Backend engineer" />
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Start" htmlFor={`${idBase}-start`} fieldKey={`${index}.start`} error={errors.start}>
          <MonthInput id={`${idBase}-start`} value={row.start} invalid={bad('start')} onChange={(start) => onChange({ start })} />
        </Field>
        <Field label="End" htmlFor={`${idBase}-end`} fieldKey={`${index}.end`} error={errors.end}>
          <MonthInput id={`${idBase}-end`} value={row.current ? '' : row.end} disabled={row.current} invalid={bad('end')} onChange={(end) => onChange({ end: end || null })} />
        </Field>
      </div>
      {/* Switching it on clears the end, so a role still held never keeps an old end month. */}
      <SwitchRow checked={row.current} onCheckedChange={(current) => onChange(current ? { current, end: null } : { current })} label="Currently working here" />
      <Field label="Description" htmlFor={`${idBase}-description`} fieldKey={`${index}.description`} error={errors.description} hint={`${row.description.length} / ${LIMITS.description} characters.`}>
        <Textarea id={`${idBase}-description`} value={row.description} maxLength={LIMITS.description} aria-invalid={bad('description')} onChange={(e) => onChange({ description: e.target.value })} placeholder="What you built and the results." />
      </Field>
    </div>
  )
}

export function ExperienceSection({ items }: { items: readonly Experience[] }) {
  return (
    <ListSection
      model={EXPERIENCE}
      title="Experience"
      noun="role"
      items={items}
      empty={{ title: 'No experience yet', description: 'Add the roles you have held: company, title, dates and what you did. Press Edit to add the first one.' }}
      ReadItem={ExperienceRead}
      EditRow={ExperienceRow}
      rowName={(row) => [row.title, row.company].filter((part) => part.trim()).join(' at ')}
    />
  )
}
