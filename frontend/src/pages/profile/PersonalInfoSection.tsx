import { useId } from 'react'
import type { PersonalInfo } from '@/api/types'
import { Field, Input, Textarea } from '@/components/ui/Field'
import { Filled, Section } from './formParts'
import { PERSONAL_LIMITS } from './limits'
import type { PersonalErrors } from './personalInfo'

interface PersonalInfoSectionProps {
  value: PersonalInfo
  onChange: (key: keyof PersonalInfo, value: string) => void
  filled: ReadonlySet<string>
  errors: PersonalErrors
}

export function PersonalInfoSection({ value, onChange, filled, errors }: PersonalInfoSectionProps) {
  const ids = { name: useId(), headline: useId(), location: useId(), summary: useId() }
  return (
    <Section title="Personal info" description="About you. Your name is shown in the sidebar.">
      <div className="grid gap-5 sm:grid-cols-2">
        <Filled on={filled.has('personal.full_name')}>
          <Field label="Full name" htmlFor={ids.name} error={errors.full_name}>
            <Input id={ids.name} value={value.full_name} maxLength={PERSONAL_LIMITS.full_name} onChange={(e) => onChange('full_name', e.target.value)} placeholder="Ada Example" />
          </Field>
        </Filled>
        <Filled on={filled.has('personal.location')}>
          <Field label="Location" htmlFor={ids.location} error={errors.location}>
            <Input id={ids.location} value={value.location} maxLength={PERSONAL_LIMITS.location} onChange={(e) => onChange('location', e.target.value)} placeholder="Berlin, Germany" />
          </Field>
        </Filled>
      </div>
      <Filled on={filled.has('personal.headline')}>
        <Field label="Headline" htmlFor={ids.headline} error={errors.headline}>
          <Input id={ids.headline} value={value.headline} maxLength={PERSONAL_LIMITS.headline} onChange={(e) => onChange('headline', e.target.value)} placeholder="Backend engineer" />
        </Field>
      </Filled>
      <Filled on={filled.has('personal.summary')}>
        <Field label="Short summary" htmlFor={ids.summary} error={errors.summary} hint={`${value.summary.length} / ${PERSONAL_LIMITS.summary} characters. A few lines about who you are.`}>
          <Textarea id={ids.summary} value={value.summary} maxLength={PERSONAL_LIMITS.summary} onChange={(e) => onChange('summary', e.target.value)} placeholder="Backend engineer with 6 years of Python…" />
        </Field>
      </Filled>
    </Section>
  )
}
