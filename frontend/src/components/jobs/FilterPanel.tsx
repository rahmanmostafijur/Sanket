import { Check } from 'lucide-react'
import { Slider } from 'radix-ui'
import type { Job } from '@/api/types'
import { activeFilterCount, EMPTY_FILTERS, toggleValue, type JobFilters } from '@/features/jobs/filters'
import { cn } from '@/lib/cn'

interface Option {
  value: string
  label: string
}

const WORK_MODE: Option[] = [
  { value: 'remote', label: 'Remote' },
  { value: 'onsite', label: 'On-site' },
  { value: 'hybrid', label: 'Hybrid' },
]
const SENIORITY: Option[] = [
  { value: 'junior', label: 'Entry Level' },
  { value: 'mid', label: 'Mid-level' },
  { value: 'senior', label: 'Senior' },
  { value: 'lead', label: 'Lead' },
]
const EMPLOYMENT: Option[] = [
  { value: 'full_time', label: 'Full-time' },
  { value: 'part_time', label: 'Part-time' },
  { value: 'contract', label: 'Contract' },
]

const SALARY_MAX = 12_000
const SALARY_STEP = 500

function count(jobs: readonly Job[], pick: (job: Job) => string | null | undefined, value: string): number {
  return jobs.filter((job) => pick(job) === value).length
}

interface GroupProps {
  title: string
  options: Option[]
  selected: readonly string[]
  counts: (value: string) => number
  onToggle: (value: string) => void
}

function CheckGroup({ title, options, selected, counts, onToggle }: GroupProps) {
  return (
    <fieldset className="space-y-2">
      <legend className="mb-2.5 text-[13.5px] font-medium text-fg">{title}</legend>
      {options.map((option) => {
        const checked = selected.includes(option.value)
        return (
          <label key={option.value} className="group flex cursor-pointer items-center gap-3 py-0.5 text-[14px]">
            <input type="checkbox" className="peer sr-only" checked={checked} onChange={() => onToggle(option.value)} />
            <span
              className={cn(
                'grid size-4 place-items-center rounded-[4px] border transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-accent/60',
                checked ? 'border-accent bg-accent text-accent-ink' : 'border-[#3a4a60] group-hover:border-muted',
              )}
            >
              {checked ? <Check className="size-3" strokeWidth={3.2} /> : null}
            </span>
            <span className={cn('flex-1', checked ? 'text-fg' : 'text-fg-2')}>{option.label}</span>
            <span className="text-[12.5px] text-muted tabular">{counts(option.value).toLocaleString()}</span>
          </label>
        )
      })}
    </fieldset>
  )
}

interface FilterPanelProps {
  filters: JobFilters
  onChange: (filters: JobFilters) => void
  /** The jobs the counts are taken from. */
  jobs: readonly Job[]
  className?: string
}

export function FilterPanel({ filters, onChange, jobs, className }: FilterPanelProps) {
  const salary = filters.minMonthlyUsd ?? 0
  return (
    <aside className={cn('rounded-[var(--radius-card)] border border-line bg-surface p-5', className)} aria-label="Filters">
      <div className="mb-5 flex items-center justify-between">
        <h2 className="text-base font-semibold text-fg">Filters</h2>
        <button
          type="button"
          disabled={activeFilterCount(filters) === 0}
          onClick={() => onChange(EMPTY_FILTERS)}
          className="text-[12.5px] text-muted transition-colors hover:text-fg disabled:opacity-50"
        >
          Reset all
        </button>
      </div>
      <div className="space-y-6">
        <CheckGroup
          title="Work Mode"
          options={WORK_MODE}
          selected={filters.workModes}
          counts={(value) => count(jobs, (job) => job.extracted?.work_mode, value)}
          onToggle={(value) => onChange({ ...filters, workModes: toggleValue(filters.workModes, value as JobFilters['workModes'][number]) })}
        />
        <CheckGroup
          title="Seniority"
          options={SENIORITY}
          selected={filters.seniorities}
          counts={(value) => count(jobs, (job) => job.extracted?.seniority, value)}
          onToggle={(value) => onChange({ ...filters, seniorities: toggleValue(filters.seniorities, value as JobFilters['seniorities'][number]) })}
        />
        <CheckGroup
          title="Employment Type"
          options={EMPLOYMENT}
          selected={filters.employmentTypes}
          counts={(value) => count(jobs, (job) => job.extracted?.employment_type, value)}
          onToggle={(value) => onChange({ ...filters, employmentTypes: toggleValue(filters.employmentTypes, value as JobFilters['employmentTypes'][number]) })}
        />
        <div>
          <p className="mb-4 text-[13.5px] font-medium text-fg">Salary Range</p>
          <Slider.Root
            className="relative flex h-5 touch-none select-none items-center"
            value={[salary]}
            max={SALARY_MAX}
            step={SALARY_STEP}
            onValueChange={([value]) => onChange({ ...filters, minMonthlyUsd: value ? value : null })}
            aria-label="Minimum monthly salary in USD"
          >
            <Slider.Track className="relative h-1 grow rounded-full bg-[#1f2a39]">
              <Slider.Range className="absolute h-full rounded-full bg-accent" />
            </Slider.Track>
            <Slider.Thumb className="block size-4 rounded-full border-2 border-accent bg-bg shadow-[0_0_10px_rgb(184_243_107/0.5)] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/25" />
          </Slider.Root>
          <p className="mt-3 text-right text-[12px] text-muted tabular">
            {salary ? `From $${(salary / 1000).toFixed(salary % 1000 ? 1 : 0)}k / month` : 'Any salary'}
          </p>
          <p className="mt-1 text-[11px] leading-snug text-subtle">USD salaries only, applied to the jobs shown.</p>
        </div>
      </div>
    </aside>
  )
}
