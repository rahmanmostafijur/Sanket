import type { Language, LanguageInput, Skill, SkillInput, SkillLevel } from '@/api/types'
import { Field, Input, NativeSelect } from '@/components/ui/Field'
import { LANGUAGES, SKILLS } from './drafts'
import { PROFICIENCY_OPTIONS, SKILL_LEVEL_OPTIONS, labelOf } from './labels'
import { ListSection, type RowEditorProps } from './ListSection'
import { TEXT_LIMITS } from './limits'

function SkillRead({ item }: { item: SkillInput }) {
  const level = labelOf(SKILL_LEVEL_OPTIONS, item.level)
  return (
    <p className="flex items-baseline justify-between gap-3 text-[14.5px] text-fg">
      <span className="font-medium">{item.name}</span>
      {level ? <span className="text-[13px] text-muted">{level}</span> : null}
    </p>
  )
}

function SkillRow({ row, index, errors, idBase, onChange }: RowEditorProps<'skills'>) {
  return (
    <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Field label="Skill" htmlFor={`${idBase}-name`} fieldKey={`${index}.name`} error={errors.name}>
        <Input id={`${idBase}-name`} value={row.name} maxLength={TEXT_LIMITS.skills.name} aria-invalid={Boolean(errors.name)} onChange={(e) => onChange({ name: e.target.value })} placeholder="Python" />
      </Field>
      <Field label="Level" htmlFor={`${idBase}-level`} fieldKey={`${index}.level`} error={errors.level} hint="Optional.">
        <NativeSelect id={`${idBase}-level`} value={row.level ?? ''} onChange={(e) => onChange({ level: e.target.value === '' ? null : (e.target.value as SkillLevel) })}>
          <option value="">Not set</option>
          {SKILL_LEVEL_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </NativeSelect>
      </Field>
    </div>
  )
}

export function SkillsSection({ items }: { items: readonly Skill[] }) {
  return (
    <ListSection
      model={SKILLS}
      title="Skills"
      noun="skill"
      items={items}
      empty={{ title: 'No skills yet', description: 'Add the tools and technologies you work with. They are used to suggest a matching profile. Press Edit to add some.' }}
      ReadItem={SkillRead}
      EditRow={SkillRow}
      rowName={(row) => row.name}
    />
  )
}

function LanguageRead({ item }: { item: LanguageInput }) {
  return (
    <p className="flex items-baseline justify-between gap-3 text-[14.5px] text-fg">
      <span className="font-medium">{item.name}</span>
      <span className="text-[13px] text-muted">{labelOf(PROFICIENCY_OPTIONS, item.proficiency)}</span>
    </p>
  )
}

function LanguageRow({ row, index, errors, idBase, onChange }: RowEditorProps<'languages'>) {
  return (
    <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Field label="Language" htmlFor={`${idBase}-name`} fieldKey={`${index}.name`} error={errors.name}>
        <Input id={`${idBase}-name`} value={row.name} maxLength={TEXT_LIMITS.languages.name} aria-invalid={Boolean(errors.name)} onChange={(e) => onChange({ name: e.target.value })} placeholder="English" />
      </Field>
      <Field label="Level" htmlFor={`${idBase}-proficiency`} fieldKey={`${index}.proficiency`} error={errors.proficiency}>
        <NativeSelect id={`${idBase}-proficiency`} value={row.proficiency} aria-invalid={Boolean(errors.proficiency)} onChange={(e) => onChange({ proficiency: e.target.value as typeof row.proficiency })}>
          <option value="">Choose</option>
          {PROFICIENCY_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </NativeSelect>
      </Field>
    </div>
  )
}

export function LanguagesSection({ items }: { items: readonly Language[] }) {
  return (
    <ListSection
      model={LANGUAGES}
      title="Languages"
      noun="language"
      items={items}
      empty={{ title: 'No languages yet', description: 'Add the languages you speak and how well. Press Edit to add one.' }}
      ReadItem={LanguageRead}
      EditRow={LanguageRow}
      rowName={(row) => row.name}
    />
  )
}
