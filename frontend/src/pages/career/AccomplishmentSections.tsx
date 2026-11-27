import { Award, FolderGit2 } from 'lucide-react'
import type { Certification, CertificationInput, Project, ProjectInput } from '@/api/types'
import { Field, Input, Textarea } from '@/components/ui/Field'
import { CERTIFICATIONS, PROJECTS } from './drafts'
import { ListSection, type RowEditorProps } from './ListSection'
import { TEXT_LIMITS } from './limits'

function href(url: string): string {
  return /^https?:\/\//i.test(url) ? url : `https://${url}`
}

function OpenLink({ url }: { url: string }) {
  return <a href={href(url)} target="_blank" rel="noopener noreferrer" className="text-[13px] font-medium text-accent hover:underline">Open link</a>
}

function CertificationRead({ item }: { item: CertificationInput }) {
  const detail = [item.issuer, item.year === null ? '' : String(item.year)].filter(Boolean).join(' · ')
  return (
    <div className="flex items-start gap-3">
      <Award className="mt-0.5 size-4 shrink-0 text-muted" />
      <div className="min-w-0">
        <p className="text-[14.5px] font-medium text-fg">{item.title}</p>
        {detail ? <p className="text-[13.5px] text-fg-2">{detail}</p> : null}
        {item.url ? <OpenLink url={item.url} /> : null}
      </div>
    </div>
  )
}

function CertificationRow({ row, index, errors, idBase, onChange }: RowEditorProps<'certifications'>) {
  const limits = TEXT_LIMITS.certifications
  return (
    <div className="space-y-4">
      <Field label="Name" htmlFor={`${idBase}-title`} fieldKey={`${index}.title`} error={errors.title}>
        <Input id={`${idBase}-title`} value={row.title} maxLength={limits.title} aria-invalid={Boolean(errors.title)} onChange={(e) => onChange({ title: e.target.value })} placeholder="Cloud practitioner" />
      </Field>
      <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Field label="Issuer" htmlFor={`${idBase}-issuer`} fieldKey={`${index}.issuer`} error={errors.issuer}>
          <Input id={`${idBase}-issuer`} value={row.issuer} maxLength={limits.issuer} aria-invalid={Boolean(errors.issuer)} onChange={(e) => onChange({ issuer: e.target.value })} placeholder="Example Institute" />
        </Field>
        <Field label="Year" htmlFor={`${idBase}-year`} fieldKey={`${index}.year`} error={errors.year}>
          <Input id={`${idBase}-year`} inputMode="numeric" value={row.year} maxLength={4} aria-invalid={Boolean(errors.year)} onChange={(e) => onChange({ year: e.target.value })} placeholder="2022" />
        </Field>
      </div>
      <Field label="Link" htmlFor={`${idBase}-url`} fieldKey={`${index}.url`} error={errors.url} hint="Optional.">
        <Input id={`${idBase}-url`} value={row.url} maxLength={limits.url} aria-invalid={Boolean(errors.url)} onChange={(e) => onChange({ url: e.target.value })} placeholder="example.com/credential" />
      </Field>
    </div>
  )
}

export function CertificationsSection({ items }: { items: readonly Certification[] }) {
  return (
    <ListSection
      model={CERTIFICATIONS}
      title="Certifications"
      noun="certification"
      items={items}
      empty={{ title: 'No certifications yet', description: 'Add certificates and courses you completed, with who issued them and when. Press Edit to add one.' }}
      ReadItem={CertificationRead}
      EditRow={CertificationRow}
      rowName={(row) => row.title}
    />
  )
}

function ProjectRead({ item }: { item: ProjectInput }) {
  return (
    <div className="flex items-start gap-3">
      <FolderGit2 className="mt-0.5 size-4 shrink-0 text-muted" />
      <div className="min-w-0">
        <p className="text-[14.5px] font-medium text-fg">{item.title}</p>
        {item.description ? <p className="mt-1 whitespace-pre-line text-[13.5px] leading-relaxed text-fg-2">{item.description}</p> : null}
        {item.url ? <OpenLink url={item.url} /> : null}
      </div>
    </div>
  )
}

function ProjectRow({ row, index, errors, idBase, onChange }: RowEditorProps<'projects'>) {
  const limits = TEXT_LIMITS.projects
  return (
    <div className="space-y-4">
      <Field label="Name" htmlFor={`${idBase}-title`} fieldKey={`${index}.title`} error={errors.title}>
        <Input id={`${idBase}-title`} value={row.title} maxLength={limits.title} aria-invalid={Boolean(errors.title)} onChange={(e) => onChange({ title: e.target.value })} placeholder="Job board crawler" />
      </Field>
      <Field label="Description" htmlFor={`${idBase}-description`} fieldKey={`${index}.description`} error={errors.description} hint={`${row.description.length} / ${limits.description} characters.`}>
        <Textarea id={`${idBase}-description`} value={row.description} maxLength={limits.description} aria-invalid={Boolean(errors.description)} onChange={(e) => onChange({ description: e.target.value })} placeholder="What it does and your part in it." />
      </Field>
      <Field label="Link" htmlFor={`${idBase}-url`} fieldKey={`${index}.url`} error={errors.url} hint="Optional.">
        <Input id={`${idBase}-url`} value={row.url} maxLength={limits.url} aria-invalid={Boolean(errors.url)} onChange={(e) => onChange({ url: e.target.value })} placeholder="github.com/ada-example/crawler" />
      </Field>
    </div>
  )
}

export function ProjectsSection({ items }: { items: readonly Project[] }) {
  return (
    <ListSection
      model={PROJECTS}
      title="Projects"
      noun="project"
      items={items}
      empty={{ title: 'No projects yet', description: 'Add things you built: a name, what it does and a link. Press Edit to add one.' }}
      ReadItem={ProjectRead}
      EditRow={ProjectRow}
      rowName={(row) => row.title}
    />
  )
}
