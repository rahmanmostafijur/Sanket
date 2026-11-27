import { CircleCheck, CircleDashed, CircleX, Info, Plus, Save, Trash } from 'lucide-react'
import { useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError, errorMessage } from '@/api/client'
import type { EmploymentType, Me, PersonalInfo, Profile, ProfileWrite, Seniority, WorkMode } from '@/api/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { Field, Input, SwitchRow, TagInput, Textarea, ToggleChips } from '@/components/ui/Field'
import { FilterMenu } from '@/components/ui/FilterMenu'
import { Card, Skeleton } from '@/components/ui/primitives'
import { ErrorState } from '@/components/ui/States'
import { useActiveProfile, useDeleteProfile, useMe, useSaveProfile, useUpdateMe } from '@/hooks/data'
import { cn } from '@/lib/cn'
import { relativeTime } from '@/lib/format'
import { useSession } from '@/stores/session'
import { toast } from '@/stores/toasts'
import { CvImport } from './CvImport'
import { filledFields, mergePersonal, mergeProfile } from './cvProposal'
import { clearFixed, errorsFromServer, errorSummary, firstInvalid, profileNameFor, validateProfile, type FieldErrors } from './formErrors'
import { Filled, Section } from './formParts'
import { LIMITS } from './limits'
import { PersonalInfoSection } from './PersonalInfoSection'
import { personalChanged, personalFrom, trimmedPersonal } from './personalInfo'
import { useCvImport } from './useCvImport'

const SENIORITY_OPTIONS: { value: Seniority; label: string }[] = [
  { value: 'intern', label: 'Intern' },
  { value: 'junior', label: 'Junior' },
  { value: 'mid', label: 'Mid-level' },
  { value: 'senior', label: 'Senior' },
  { value: 'lead', label: 'Lead' },
]
const WORK_MODE_OPTIONS: { value: WorkMode; label: string }[] = [
  { value: 'remote', label: 'Remote' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'onsite', label: 'On-site' },
]
const EMPLOYMENT_OPTIONS: { value: EmploymentType; label: string }[] = [
  { value: 'full_time', label: 'Full-time' },
  { value: 'part_time', label: 'Part-time' },
  { value: 'contract', label: 'Contract' },
  { value: 'internship', label: 'Internship' },
]

const EMPTY: ProfileWrite = {
  name: '',
  active: true,
  desired_titles: [],
  required_skills: [],
  preferred_skills: [],
  seniorities: [],
  work_modes: [],
  employment_types: [],
  countries: [],
  locations: [],
  summary: '',
  min_score_override: null,
}

function toWrite(profile: Profile): ProfileWrite {
  return {
    name: profile.name,
    active: profile.active,
    desired_titles: profile.desired_titles,
    required_skills: profile.required_skills,
    preferred_skills: profile.preferred_skills,
    seniorities: profile.seniorities,
    work_modes: profile.work_modes,
    employment_types: profile.employment_types,
    countries: profile.countries,
    locations: profile.locations,
    summary: profile.summary,
    min_score_override: profile.min_score_override,
  }
}

function countryCode(raw: string): string | null {
  const code = raw.trim().toUpperCase()
  return /^[A-Z]{2}$/.test(code) ? code : null
}

interface StatusView {
  icon: ReactNode
  text: string
  className: string
  /** Why the profile is not ready yet, when the API says. */
  note?: string
}

const PENDING_ICON = <CircleDashed className="size-4 animate-spin [animation-duration:3s]" />
const PENDING_STYLE = 'text-amber border-amber/25 bg-amber/[0.07]'

function statusOf(profile: Profile): StatusView {
  switch (profile.embedding_status) {
    case 'ready':
      return { icon: <CircleCheck className="size-4" />, text: 'Ready: being matched', className: 'text-accent border-accent/25 bg-accent/[0.07]' }
    case 'failed':
      return { icon: <CircleX className="size-4" />, text: 'Preparation failed: retrying', className: 'text-danger border-danger/30 bg-danger/[0.07]' }
    case 'pending':
      if (profile.embedding_note === 'quota') {
        return {
          icon: PENDING_ICON,
          text: 'Matching is delayed: will retry',
          className: PENDING_STYLE,
          note: 'The language-model quota is used up for now. Sanket retries automatically; nothing is lost.',
        }
      }
      return {
        icon: PENDING_ICON,
        text: 'Preparing for matching',
        className: PENDING_STYLE,
        note: profile.embedding_note === 'error' ? 'A step failed; retrying automatically.' : undefined,
      }
  }
}

interface EditorProps {
  /** The signed-in account, or null for a credential that is not an account (the personal section is then hidden). */
  me: Me | null
  profile: Profile | null
  profiles: Profile[]
  /** True while a new profile is being written: asked for, or because there is no saved profile yet. */
  creating: boolean
  /** Whether at least one profile is saved. Only then can a new one be started or cancelled. */
  hasSaved: boolean
  setCreating: (creating: boolean) => void
}

export default function ProfilePage() {
  const { profile, profiles, isLoading, error } = useActiveProfile()
  const me = useMe()
  const [creating, setCreating] = useState(false)
  if (isLoading || me.isLoading) return <div className="mx-auto max-w-[980px] space-y-4 pt-4"><Skeleton className="h-24 rounded-[14px]" /><Skeleton className="h-96 rounded-[14px]" /></div>
  if (error) return <ErrorState error={error} className="py-20" />
  // With nothing saved the page opens straight in the create state.
  const hasSaved = profiles.length > 0
  const creatingNow = creating || !hasSaved
  const editing = creatingNow ? null : profile
  // A new key per profile version resets the form to what is stored.
  return <ProfileEditor key={editing ? `${editing.id}:${editing.updated_at}` : 'new'} me={me.data ?? null} profile={profile} profiles={profiles} creating={creatingNow} hasSaved={hasSaved} setCreating={setCreating} />
}

function ProfileEditor({ me, profile, profiles, creating, hasSaved, setCreating }: EditorProps) {
  const setActive = useSession((s) => s.setActiveProfileId)
  const save = useSaveProfile()
  const saveMe = useUpdateMe()
  const remove = useDeleteProfile()
  const formRef = useRef<HTMLFormElement>(null)
  const editing = creating ? null : profile
  const [form, setForm] = useState<ProfileWrite>(() => (editing ? toWrite(editing) : EMPTY))
  const [personal, setPersonal] = useState<PersonalInfo>(() => personalFrom(me))
  // Problems by field, shown next to the field; `problem` is for what no single field owns.
  const [errors, setErrors] = useState<FieldErrors>({})
  // Fields the CV filled, until the user edits them; the count feeds the banner until it is dismissed.
  const [filled, setFilled] = useState<ReadonlySet<string>>(new Set())
  const [importedCount, setImportedCount] = useState<number | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const ids = { name: useId(), titles: useId(), required: useId(), preferred: useId(), countries: useId(), locations: useId(), summary: useId() }

  const unmark = (field: string) =>
    setFilled((current) => {
      if (!current.has(field)) return current
      const next = new Set(current)
      next.delete(field)
      return next
    })
  const set = <K extends keyof ProfileWrite>(key: K, value: ProfileWrite[K]) => {
    const next = { ...form, [key]: value }
    setForm(next)
    setErrors((current) => clearFixed(current, `profile.${key}`, next))
    unmark(`profile.${key}`)
  }
  const setPersonalField = (key: keyof PersonalInfo, value: string) => {
    setPersonal((current) => ({ ...current, [key]: value }))
    setErrors((current) => clearFixed(current, `personal.${key}`, form))
    unmark(`personal.${key}`)
  }

  const cv = useCvImport((proposal) => {
    // Only what the CV states is written over the form; nothing is saved until Save.
    if (me) setPersonal((current) => mergePersonal(current, proposal.personal))
    setForm((current) => mergeProfile(current, proposal.profile))
    const fields = filledFields(proposal, me !== null)
    setFilled(new Set(fields))
    setImportedCount(fields.length)
  })
  const busy = cv.pending || saveMe.isPending || save.isPending

  const takenNames = profiles.filter((p) => p.id !== editing?.id).map((p) => p.name)
  // What the profile is called if its name is left empty: the headline, else "My profile".
  const defaultName = profileNameFor('', personal.headline, takenNames)

  /** Moves to the field and focuses it, so a person never has to hunt for what is wrong. */
  const focusField = (key: string | null) => {
    if (!key) return
    const field = formRef.current?.querySelector<HTMLElement>(`[data-field="${key}"]`)
    field?.querySelector<HTMLElement>('input, textarea, button')?.focus()
    field?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  }
  const showErrors = (found: FieldErrors, fallback: string) => {
    setErrors(found)
    const first = firstInvalid(found)
    if (first) focusField(first)
    else setProblem(fallback)
  }

  /** Throws away what was typed or imported and goes back to the saved profile (or the empty form). */
  const discard = () => {
    setForm(profile ? toWrite(profile) : EMPTY)
    setPersonal(personalFrom(me))
    setErrors({})
    setProblem(null)
    setFilled(new Set())
    setImportedCount(null)
    cv.reset()
    setCreating(false)
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setProblem(null)
    const invalid = validateProfile(form)
    setErrors(invalid)
    if (firstInvalid(invalid)) {
      focusField(firstInvalid(invalid))
      return
    }
    // The account is saved first so the sidebar name is right as soon as the profile is saved.
    if (me && personalChanged(personal, me)) {
      try {
        await saveMe.mutateAsync(trimmedPersonal(personal))
      } catch (failure) {
        showErrors(errorsFromServer(failure, 'personal'), errorMessage(failure))
        return
      }
    }
    save.mutate(
      { id: editing?.id ?? null, profile: { ...form, name: profileNameFor(form.name, personal.headline, takenNames), summary: form.summary.trim() } },
      {
        onSuccess: () => {
          setCreating(false)
          toast({ tone: 'success', title: editing ? 'Profile saved' : 'Profile created', description: 'Matching uses it once it is prepared.' })
        },
        onError: (failure) => {
          const found = errorsFromServer(failure, 'profile')
          if (failure instanceof ApiError && failure.status === 409 && !found['profile.name']) found['profile.name'] = failure.message
          showErrors(found, errorMessage(failure))
        },
      },
    )
  }

  const destroy = () => {
    if (!editing) return
    remove.mutate(editing.id, {
      onSuccess: () => {
        setActive(null)
        toast({ title: 'Profile deleted', description: 'Its matches were deleted with it.' })
      },
      onError: (failure) => toast({ tone: 'error', title: 'Could not delete', description: errorMessage(failure) }),
    })
  }

  const status = editing ? statusOf(editing) : null
  const topMessage = errorSummary(errors) ?? problem
  const error = (key: string) => errors[`profile.${key}`]

  return (
    <form ref={formRef} onSubmit={(event) => void submit(event)} className="mx-auto max-w-[980px]" noValidate>
      <PageHeader
        title="My Profile"
        description="What you are looking for. Sanket scores every new job against it and streams the good ones to you."
        actions={
          <>
            {profiles.length > 1 && !creating ? (
              <FilterMenu
                label="Profile"
                summary={profile?.name ?? 'Choose'}
                options={profiles.map((p) => ({ value: p.id, label: p.name }))}
                value={profile?.id ?? 0}
                onChange={(id) => setActive(id)}
              />
            ) : null}
            {hasSaved && !creating ? <Button variant="outline" onClick={() => setCreating(true)}><Plus /> New profile</Button> : null}
            {hasSaved && creating ? <Button variant="secondary" onClick={discard}>Cancel</Button> : null}
            <Button type="submit" variant="primary" disabled={busy}><Save /> {editing ? 'Save changes' : 'Create profile'}</Button>
          </>
        }
      />

      {status && editing ? (
        <div className="mb-5 flex flex-wrap items-center gap-3 text-[13px]">
          <span className={cn('inline-flex h-7 items-center gap-1.5 rounded-full border px-3 font-medium', status.className)}>{status.icon}{status.text}</span>
          <span className="text-subtle">Updated {relativeTime(editing.updated_at)}</span>
          {status.note ? <p className="basis-full text-[13px] text-muted">{status.note}</p> : null}
        </div>
      ) : null}
      {topMessage ? <p role="alert" className="mb-5 rounded-xl border border-danger/30 bg-danger/[0.07] px-4 py-3 text-[13.5px] text-danger">{topMessage}</p> : null}

      <CvImport cv={cv} filledCount={importedCount} onDismiss={() => setImportedCount(null)} />

      <div className="space-y-5">
        {me ? <PersonalInfoSection value={personal} onChange={setPersonalField} filled={filled} errors={errors} /> : null}

        <Section title="Basics">
          <Field label="Profile name" htmlFor={ids.name} fieldKey="profile.name" error={error('name')} hint={`Optional. Left empty, the profile is called “${defaultName}”. Name it yourself if you keep several.`}>
            <Input id={ids.name} value={form.name} maxLength={LIMITS.name} aria-invalid={Boolean(error('name'))} onChange={(e) => set('name', e.target.value)} placeholder={defaultName} />
          </Field>
          <SwitchRow checked={form.active} onCheckedChange={(v) => set('active', v)} label="Active" description="Inactive profiles keep their matches but receive no new ones." />
        </Section>

        <Section title="Roles and skills" description="Required skills are a hard filter; preferred skills raise the score.">
          <Filled on={filled.has('profile.desired_titles')}>
            <Field label="Preferred roles" htmlFor={ids.titles} fieldKey="profile.desired_titles" error={error('desired_titles')} hint={`Up to ${LIMITS.titles}. Press Enter after each.`}>
              <TagInput id={ids.titles} value={form.desired_titles} onChange={(v) => set('desired_titles', v)} max={LIMITS.titles} maxLength={100} placeholder="Senior Backend Engineer" />
            </Field>
          </Filled>
          <Filled on={filled.has('profile.required_skills')}>
            <Field label="Required skills" htmlFor={ids.required} fieldKey="profile.required_skills" error={error('required_skills')} hint={`Up to ${LIMITS.required}. A job must list them to match.`}>
              <TagInput id={ids.required} value={form.required_skills} onChange={(v) => set('required_skills', v)} max={LIMITS.required} tone="accent" placeholder="Python" />
            </Field>
          </Filled>
          <Filled on={filled.has('profile.preferred_skills')}>
            <Field label="Preferred skills" htmlFor={ids.preferred} fieldKey="profile.preferred_skills" error={error('preferred_skills')} hint={`Up to ${LIMITS.preferred}.`}>
              <TagInput id={ids.preferred} value={form.preferred_skills} onChange={(v) => set('preferred_skills', v)} max={LIMITS.preferred} tone="info" placeholder="Docker" />
            </Field>
          </Filled>
        </Section>

        <Section title="Work preferences" description="Leave a group empty to accept anything.">
          <Filled on={filled.has('profile.seniorities')}>
            <Field label="Seniority"><ToggleChips label="Seniority" options={SENIORITY_OPTIONS} value={form.seniorities} onChange={(v) => set('seniorities', v)} /></Field>
          </Filled>
          <Filled on={filled.has('profile.work_modes')}>
            <Field label="Work mode"><ToggleChips label="Work mode" options={WORK_MODE_OPTIONS} value={form.work_modes} onChange={(v) => set('work_modes', v)} /></Field>
          </Filled>
          <Filled on={filled.has('profile.employment_types')}>
            <Field label="Employment type"><ToggleChips label="Employment type" options={EMPLOYMENT_OPTIONS} value={form.employment_types} onChange={(v) => set('employment_types', v)} /></Field>
          </Filled>
          <div className="grid gap-5 sm:grid-cols-2">
            <Filled on={filled.has('profile.countries')}>
              <Field label="Countries" htmlFor={ids.countries} fieldKey="profile.countries" error={error('countries')} hint="Two-letter codes, e.g. DE, BD, US.">
                <TagInput id={ids.countries} value={form.countries} onChange={(v) => set('countries', v)} max={LIMITS.countries} maxLength={2} normalize={countryCode} placeholder="DE" />
              </Field>
            </Filled>
            <Filled on={filled.has('profile.locations')}>
              <Field label="Locations" htmlFor={ids.locations} fieldKey="profile.locations" error={error('locations')} hint="Places that count as a location match.">
                <TagInput id={ids.locations} value={form.locations} onChange={(v) => set('locations', v)} max={LIMITS.locations} maxLength={100} placeholder="Berlin" />
              </Field>
            </Filled>
          </div>
        </Section>

        <Section title="What you are looking for" description="A short note on the roles you want improves semantic matching.">
          <Filled on={filled.has('profile.summary')}>
            <Field label="What you are looking for" htmlFor={ids.summary} fieldKey="profile.summary" error={error('summary')} hint={`${form.summary.length} / ${LIMITS.summary} characters. The roles, domains and setup you want next.`}>
              <Textarea id={ids.summary} value={form.summary} maxLength={LIMITS.summary} aria-invalid={Boolean(error('summary'))} onChange={(e) => set('summary', e.target.value)} placeholder="Senior backend roles in Python, remote or hybrid in Berlin…" />
            </Field>
          </Filled>
          <SwitchRow
            checked={form.min_score_override !== null}
            onCheckedChange={(on) => set('min_score_override', on ? 0.6 : null)}
            label="Custom match threshold"
            description="Only keep matches at or above your own minimum score instead of the server default."
          />
          {form.min_score_override !== null ? (
            <div className="flex items-center gap-4">
              <input type="range" min={0} max={100} step={1} value={Math.round(form.min_score_override * 100)} onChange={(e) => set('min_score_override', Number(e.target.value) / 100)} aria-label="Minimum match score" className="flex-1 accent-[var(--color-accent)]" />
              <span className="w-12 text-right text-[14px] font-medium text-fg tabular">{Math.round(form.min_score_override * 100)}%</span>
            </div>
          ) : null}
          <p className="flex gap-2 text-[12.5px] leading-relaxed text-subtle"><Info className="mt-0.5 size-3.5 shrink-0" />Years of experience and salary expectations are not part of the matching profile in this version of the API.</p>
        </Section>

        {editing ? (
          <Card className="flex flex-wrap items-center justify-between gap-4 border-danger/20 p-5 sm:p-6">
            <div>
              <h2 className="text-[15px] font-semibold text-fg">Delete this profile</h2>
              <p className="mt-1 text-[13px] text-muted">Deletes the profile and all of its matches. This cannot be undone.</p>
            </div>
            <Button variant="danger" onClick={() => setConfirmDelete(true)}><Trash /> Delete profile</Button>
            <ConfirmDialog
              open={confirmDelete}
              onOpenChange={setConfirmDelete}
              title="Delete this profile?"
              description="Deletes the profile and all of its matches. This cannot be undone."
              cancelLabel="Keep it"
              confirmLabel={<><Trash /> Yes, delete</>}
              onConfirm={destroy}
              pending={remove.isPending}
            />
          </Card>
        ) : null}
      </div>
    </form>
  )
}
