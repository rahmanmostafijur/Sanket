import { UserRound } from 'lucide-react'
import { useId, useRef, useState } from 'react'
import { errorMessage } from '@/api/client'
import type { CareerPersonal } from '@/api/types'
import { EmptyState } from '@/components/ui/States'
import { Field, Input, NativeSelect, Textarea } from '@/components/ui/Field'
import { useSaveCareerPersonal } from '@/hooks/career'
import { toast } from '@/stores/toasts'
import { Filled } from '../profile/formParts'
import { useCvDraft } from './cvDraft'
import { mergePersonal } from './cvMerge'
import { errorsFromServer, errorSummary, firstInvalid, withoutError, type FieldErrors, type FieldInfo } from './fieldErrors'
import { AVAILABILITY_OPTIONS, countryName, labelOf } from './labels'
import { PERSONAL_LIMITS } from './limits'
import { focusField } from './focusField'
import { CvBanner, SectionCard } from './SectionCard'
import { validatePersonal } from './validate'

const FIELDS: readonly FieldInfo[] = [
  { key: 'full_name', label: 'Full name' },
  { key: 'headline', label: 'Headline' },
  { key: 'summary', label: 'Summary' },
  { key: 'country', label: 'Country' },
  { key: 'city', label: 'City' },
  { key: 'github_url', label: 'GitHub' },
  { key: 'linkedin_url', label: 'LinkedIn' },
  { key: 'portfolio_url', label: 'Portfolio' },
  { key: 'availability', label: 'Availability' },
]

const LINKS: readonly { key: 'github_url' | 'linkedin_url' | 'portfolio_url'; label: string; placeholder: string }[] = [
  { key: 'github_url', label: 'GitHub', placeholder: 'github.com/ada-example' },
  { key: 'linkedin_url', label: 'LinkedIn', placeholder: 'linkedin.com/in/ada-example' },
  { key: 'portfolio_url', label: 'Portfolio', placeholder: 'ada.example.com' },
]

/** What is sent: text trimmed and the country upper-cased. */
function normalized(personal: CareerPersonal): CareerPersonal {
  return {
    ...personal,
    full_name: personal.full_name.trim(),
    headline: personal.headline.trim(),
    summary: personal.summary.trim(),
    country: personal.country.trim().toUpperCase(),
    city: personal.city.trim(),
    github_url: personal.github_url.trim(),
    linkedin_url: personal.linkedin_url.trim(),
    portfolio_url: personal.portfolio_url.trim(),
  }
}

function href(url: string): string {
  return /^https?:\/\//i.test(url) ? url : `https://${url}`
}

function PersonalRead({ personal }: { personal: CareerPersonal }) {
  const country = countryName(personal.country)
  const place = [personal.city, country ? `${country} (${personal.country})` : personal.country].filter(Boolean).join(', ')
  const links = LINKS.filter((link) => personal[link.key])
  const rows: [string, string][] = [
    ['Full name', personal.full_name],
    ['Headline', personal.headline],
    ['Location', place],
    ['Availability', labelOf(AVAILABILITY_OPTIONS, personal.availability)],
  ]
  const shown = rows.filter(([, value]) => value)
  if (!shown.length && !personal.summary && !links.length) {
    return (
      <EmptyState
        className="py-8"
        icon={<UserRound />}
        title="No personal details yet"
        description="Add your name, a headline, a short summary and where you are based. Press Edit to start."
      />
    )
  }
  return (
    <div className="space-y-4">
      <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
        {shown.map(([label, value]) => (
          <div key={label}>
            <dt className="text-[12.5px] text-subtle">{label}</dt>
            <dd className="mt-0.5 text-[14.5px] text-fg">{value}</dd>
          </div>
        ))}
      </dl>
      {personal.summary ? <p className="whitespace-pre-line text-[14px] leading-relaxed text-fg-2">{personal.summary}</p> : null}
      {links.length ? (
        <ul className="flex flex-wrap gap-x-5 gap-y-1.5 text-[13.5px]">
          {links.map((link) => (
            <li key={link.key}>
              <a href={href(personal[link.key])} target="_blank" rel="noopener noreferrer" className="font-medium text-accent hover:underline">{link.label}</a>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

/** The personal part of the career profile. */
export function PersonalSection({ personal }: { personal: CareerPersonal }) {
  const { proposal, clear } = useCvDraft()
  const save = useSaveCareerPersonal()
  const formRef = useRef<HTMLFormElement>(null)
  // A CV that stated something opens the editor with those values merged in; nothing is saved yet.
  const [merged] = useState(() => {
    const merge = proposal ? mergePersonal(personal, proposal.personal) : null
    return merge && merge.filled.length ? merge : null
  })
  const [editing, setEditing] = useState(merged !== null)
  const [draft, setDraft] = useState<CareerPersonal>(merged?.value ?? personal)
  const [filled, setFilled] = useState<ReadonlySet<string>>(new Set(merged?.filled))
  const [bannerCount, setBannerCount] = useState<number | null>(merged?.filled.length ?? null)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [problem, setProblem] = useState<string | null>(null)
  const ids = { name: useId(), headline: useId(), summary: useId(), country: useId(), city: useId(), github: useId(), linkedin: useId(), portfolio: useId(), availability: useId() }

  const close = () => {
    clear('personal')
    setEditing(false)
    setErrors({})
    setProblem(null)
    setFilled(new Set())
    setBannerCount(null)
  }
  const edit = () => {
    setDraft(personal)
    setEditing(true)
  }
  const cancel = () => {
    setDraft(personal)
    close()
  }
  const change = <K extends keyof CareerPersonal>(key: K, value: CareerPersonal[K]) => {
    setDraft((current) => ({ ...current, [key]: value }))
    setErrors((current) => withoutError(current, key))
    setFilled((current) => {
      if (!current.has(key)) return current
      const next = new Set(current)
      next.delete(key)
      return next
    })
  }
  const showErrors = (found: FieldErrors, fallback: string) => {
    setErrors(found)
    const first = firstInvalid(found, FIELDS)
    setProblem(first ? null : fallback)
    focusField(formRef.current, first)
  }
  const submit = () => {
    const body = normalized(draft)
    const invalid = validatePersonal(body)
    if (firstInvalid(invalid, FIELDS)) {
      showErrors(invalid, '')
      return
    }
    setErrors({})
    setProblem(null)
    save.mutate(body, {
      onSuccess: () => {
        close()
        toast({ tone: 'success', title: 'Personal details saved' })
      },
      onError: (failure) => showErrors(errorsFromServer(failure, FIELDS, false), errorMessage(failure)),
    })
  }

  const error = (key: string) => errors[key]
  const country = countryName(draft.country)
  return (
    <SectionCard
      title="Personal"
      description="Your name and headline are also shown in the sidebar. This profile is private to you."
      editing={editing}
      onEdit={edit}
      onCancel={cancel}
      onSubmit={submit}
      saving={save.isPending}
      formRef={formRef}
      message={errorSummary(errors, FIELDS) ?? problem}
      banner={bannerCount !== null ? <CvBanner count={bannerCount} unit="field" onDismiss={() => setBannerCount(null)} /> : null}
      read={<PersonalRead personal={personal} />}
      editor={
        <>
          <Filled on={filled.has('full_name')}>
            <Field label="Full name" htmlFor={ids.name} fieldKey="full_name" error={error('full_name')}>
              <Input id={ids.name} value={draft.full_name} maxLength={PERSONAL_LIMITS.full_name} aria-invalid={Boolean(error('full_name'))} onChange={(e) => change('full_name', e.target.value)} placeholder="Ada Example" />
            </Field>
          </Filled>
          <Filled on={filled.has('headline')}>
            <Field label="Headline" htmlFor={ids.headline} fieldKey="headline" error={error('headline')} hint="Also names your matching profile when you leave its name empty.">
              <Input id={ids.headline} value={draft.headline} maxLength={PERSONAL_LIMITS.headline} aria-invalid={Boolean(error('headline'))} onChange={(e) => change('headline', e.target.value)} placeholder="Backend engineer" />
            </Field>
          </Filled>
          <Filled on={filled.has('summary')}>
            <Field label="Summary" htmlFor={ids.summary} fieldKey="summary" error={error('summary')} hint={`${draft.summary.length} / ${PERSONAL_LIMITS.summary} characters.`}>
              <Textarea id={ids.summary} value={draft.summary} maxLength={PERSONAL_LIMITS.summary} aria-invalid={Boolean(error('summary'))} onChange={(e) => change('summary', e.target.value)} placeholder="Backend engineer with six years of Python..." />
            </Field>
          </Filled>
          <div className="grid gap-5 sm:grid-cols-2">
            <Filled on={filled.has('country')}>
              <Field label="Country" htmlFor={ids.country} fieldKey="country" error={error('country')} hint={country ?? 'Two-letter code, such as DE or BD.'}>
                <Input id={ids.country} value={draft.country} maxLength={2} aria-invalid={Boolean(error('country'))} onChange={(e) => change('country', e.target.value.toUpperCase())} placeholder="DE" />
              </Field>
            </Filled>
            <Filled on={filled.has('city')}>
              <Field label="City" htmlFor={ids.city} fieldKey="city" error={error('city')}>
                <Input id={ids.city} value={draft.city} maxLength={PERSONAL_LIMITS.city} aria-invalid={Boolean(error('city'))} onChange={(e) => change('city', e.target.value)} placeholder="Berlin" />
              </Field>
            </Filled>
          </div>
          {LINKS.map((link) => {
            const id = { github_url: ids.github, linkedin_url: ids.linkedin, portfolio_url: ids.portfolio }[link.key]
            return (
              <Filled key={link.key} on={filled.has(link.key)}>
                <Field label={link.label} htmlFor={id} fieldKey={link.key} error={error(link.key)}>
                  <Input id={id} value={draft[link.key]} maxLength={PERSONAL_LIMITS.url} aria-invalid={Boolean(error(link.key))} onChange={(e) => change(link.key, e.target.value)} placeholder={link.placeholder} />
                </Field>
              </Filled>
            )
          })}
          <Field label="Availability" htmlFor={ids.availability} fieldKey="availability" error={error('availability')} hint="Shown on the Overview too.">
            <NativeSelect id={ids.availability} value={draft.availability ?? ''} onChange={(e) => change('availability', e.target.value === '' ? null : (e.target.value as CareerPersonal['availability']))}>
              <option value="">Not set</option>
              {AVAILABILITY_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </NativeSelect>
          </Field>
        </>
      }
    />
  )
}
