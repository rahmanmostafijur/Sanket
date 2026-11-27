import { useId } from 'react'
import type { PersonalInfo } from '@/api/types'
import { Field, Input, Textarea } from '@/components/ui/Field'
import type { FieldErrors } from './formErrors'
import { Filled, Section } from './formParts'
import { PERSONAL_LIMITS } from './limits'

interface PersonalInfoSectionProps {
  value: PersonalInfo
  onChange: (key: keyof PersonalInfo, value: string) => void
  filled: ReadonlySet<string>
  errors: FieldErrors
}

export function PersonalInfoSection({ value, onChange, filled, errors }: PersonalInfoSectionProps) {
  const ids = { name: useId(), headline: useId(), location: useId(), summary: useId() }
  const error = (key: keyof PersonalInfo) => errors[`personal.${key}`]
  return (
    <Section title="Personal info" description="About you. Your full name is shown in the sidebar.">
      <Filled on={filled.has('personal.full_name')}>
        <Field label="Full name" htmlFor={ids.name} fieldKey="personal.full_name" error={error('full_name')}>
          <Input id={ids.name} value={value.full_name} maxLength={PERSONAL_LIMITS.full_name} aria-invalid={Boolean(error('full_name'))} onChange={(e) => onChange('full_name', e.target.value)} placeholder="Ada Example" />
        </Field>
      </Filled>
      <div className="grid gap-5 sm:grid-cols-2">
        <Filled on={filled.has('personal.headline')}>
          <Field label="Headline" htmlFor={ids.headline} fieldKey="personal.headline" error={error('headline')} hint="Also names your profile if you leave its name empty.">
            <Input id={ids.headline} value={value.headline} maxLength={PERSONAL_LIMITS.headline} aria-invalid={Boolean(error('headline'))} onChange={(e) => onChange('headline', e.target.value)} placeholder="Backend engineer" />
          </Field>
        </Filled>
        <Filled on={filled.has('personal.location')}>
          <Field label="Location" htmlFor={ids.location} fieldKey="personal.location" error={error('location')}>
            <Input id={ids.location} value={value.location} maxLength={PERSONAL_LIMITS.location} aria-invalid={Boolean(error('location'))} onChange={(e) => onChange('location', e.target.value)} placeholder="Berlin, Germany" />
          </Field>
        </Filled>
      </div>
      <Filled on={filled.has('personal.summary')}>
        <Field label="Short summary" htmlFor={ids.summary} fieldKey="personal.summary" error={error('summary')} hint={`${value.summary.length} / ${PERSONAL_LIMITS.summary} characters. A few lines about who you are.`}>
          <Textarea id={ids.summary} value={value.summary} maxLength={PERSONAL_LIMITS.summary} aria-invalid={Boolean(error('summary'))} onChange={(e) => onChange('summary', e.target.value)} placeholder="Backend engineer with 6 years of Python…" />
        </Field>
      </Filled>
    </Section>
  )
}
