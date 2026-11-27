import { GraduationCap } from 'lucide-react'
import type { Education, EducationInput } from '@/api/types'
import { Field, Input } from '@/components/ui/Field'
import { EDUCATION } from './drafts'
import { ListSection, type RowEditorProps } from './ListSection'
import { TEXT_LIMITS } from './limits'
import { formatRange } from './months'
import { MonthInput } from './MonthInput'

const LIMITS = TEXT_LIMITS.education

function EducationRead({ item }: { item: EducationInput }) {
  const title = [item.degree, item.field].filter(Boolean).join(', ')
  return (
    <div className="flex items-start gap-3">
      <GraduationCap className="mt-0.5 size-4 shrink-0 text-muted" />
      <div className="min-w-0">
        <p className="text-[14.5px] font-medium text-fg">{item.institution}</p>
        {title ? <p className="text-[13.5px] text-fg-2">{title}</p> : null}
        <p className="text-[13px] text-muted">{formatRange(item.start, item.end)}{item.grade ? ` · ${item.grade}` : ''}</p>
      </div>
    </div>
  )
}

function EducationRow({ row, index, errors, idBase, onChange }: RowEditorProps<'education'>) {
  const bad = (field: string) => Boolean(errors[field])
  return (
    <div className="space-y-4">
      <Field label="Institution" htmlFor={`${idBase}-institution`} fieldKey={`${index}.institution`} error={errors.institution}>
        <Input id={`${idBase}-institution`} value={row.institution} maxLength={LIMITS.institution} aria-invalid={bad('institution')} onChange={(e) => onChange({ institution: e.target.value })} placeholder="Example University" />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Degree" htmlFor={`${idBase}-degree`} fieldKey={`${index}.degree`} error={errors.degree}>
          <Input id={`${idBase}-degree`} value={row.degree} maxLength={LIMITS.degree} aria-invalid={bad('degree')} onChange={(e) => onChange({ degree: e.target.value })} placeholder="BSc" />
        </Field>
        <Field label="Field of study" htmlFor={`${idBase}-field`} fieldKey={`${index}.field`} error={errors.field}>
          <Input id={`${idBase}-field`} value={row.field} maxLength={LIMITS.field} aria-invalid={bad('field')} onChange={(e) => onChange({ field: e.target.value })} placeholder="Computer science" />
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Start" htmlFor={`${idBase}-start`} fieldKey={`${index}.start`} error={errors.start}>
          <MonthInput id={`${idBase}-start`} value={row.start} invalid={bad('start')} onChange={(start) => onChange({ start })} />
        </Field>
        <Field label="End" htmlFor={`${idBase}-end`} fieldKey={`${index}.end`} error={errors.end} hint="Leave empty if ongoing.">
          <MonthInput id={`${idBase}-end`} value={row.end} invalid={bad('end')} onChange={(end) => onChange({ end: end || null })} />
        </Field>
        <Field label="Grade" htmlFor={`${idBase}-grade`} fieldKey={`${index}.grade`} error={errors.grade}>
          <Input id={`${idBase}-grade`} value={row.grade} maxLength={LIMITS.grade} aria-invalid={bad('grade')} onChange={(e) => onChange({ grade: e.target.value })} placeholder="First class" />
        </Field>
      </div>
    </div>
  )
}

export function EducationSection({ items }: { items: readonly Education[] }) {
  return (
    <ListSection
      model={EDUCATION}
      title="Education"
      noun="education entry"
      items={items}
      empty={{ title: 'No education yet', description: 'Add your degrees and courses: the institution, what you studied and when. Press Edit to add the first one.' }}
      ReadItem={EducationRead}
      EditRow={EducationRow}
      rowName={(row) => row.institution}
    />
  )
}
