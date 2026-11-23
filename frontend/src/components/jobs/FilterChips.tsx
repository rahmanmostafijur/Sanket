import type { EmploymentType, Seniority, WorkMode } from '@/api/types'
import { FilterMenu, type MenuOption } from '@/components/ui/FilterMenu'
import { SALARY_STEPS, type JobFilters } from '@/features/jobs/filters'
import { cn } from '@/lib/cn'
import { SOURCES } from '@/lib/sources'

export type SortKey = 'relevance' | 'match' | 'newest' | 'salary'

const WORK_MODES: MenuOption<WorkMode>[] = [
  { value: 'remote', label: 'Remote' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'onsite', label: 'On-site' },
]
const SENIORITIES: MenuOption<Seniority>[] = [
  { value: 'intern', label: 'Intern' },
  { value: 'junior', label: 'Junior' },
  { value: 'mid', label: 'Mid-level' },
  { value: 'senior', label: 'Senior' },
  { value: 'lead', label: 'Lead' },
]
const TYPES: MenuOption<EmploymentType>[] = [
  { value: 'full_time', label: 'Full-time' },
  { value: 'part_time', label: 'Part-time' },
  { value: 'contract', label: 'Contract' },
  { value: 'internship', label: 'Internship' },
]
const SALARIES: MenuOption<number>[] = [
  { value: 0, label: 'Any salary' },
  ...SALARY_STEPS.map((step) => ({ value: step, label: `From $${step / 1000}k / month` })),
]
const SOURCE_OPTIONS: MenuOption<string>[] = SOURCES.map((source) => ({ value: source.id, label: source.name }))
const SORT_LABELS: Record<SortKey, string> = { relevance: 'Relevance', match: 'Best match', newest: 'Newest', salary: 'Salary' }

function summarize<T extends string>(fallback: string, options: readonly MenuOption<T>[], value: readonly T[]): string {
  if (value.length === 0) return fallback
  const first = options.find((option) => option.value === value[0])?.label ?? String(value[0])
  return value.length === 1 ? first : first
}

interface FilterChipsProps {
  filters: JobFilters
  onChange: (filters: JobFilters) => void
  sort: SortKey
  onSortChange: (sort: SortKey) => void
  sortOptions?: readonly SortKey[]
  /** Hide filters a page applies elsewhere (e.g. work mode as tabs). */
  hide?: readonly ('workModes' | 'sources')[]
  className?: string
}

export function FilterChips({ filters, onChange, sort, onSortChange, sortOptions = ['relevance', 'match', 'newest', 'salary'], hide = [], className }: FilterChipsProps) {
  const salary = filters.minMonthlyUsd ?? 0
  return (
    <div className={cn('flex flex-wrap items-center gap-2.5', className)}>
      {hide.includes('workModes') ? null : (
        <FilterMenu multiple label="Work mode" summary={summarize('Work mode', WORK_MODES, filters.workModes)} options={WORK_MODES} value={filters.workModes} onChange={(workModes) => onChange({ ...filters, workModes })} />
      )}
      <FilterMenu multiple label="Seniority" summary={summarize('Seniority', SENIORITIES, filters.seniorities)} options={SENIORITIES} value={filters.seniorities} onChange={(seniorities) => onChange({ ...filters, seniorities })} />
      <FilterMenu multiple label="Employment type" summary={summarize('Type', TYPES, filters.employmentTypes)} options={TYPES} value={filters.employmentTypes} onChange={(employmentTypes) => onChange({ ...filters, employmentTypes })} />
      <FilterMenu
        label="Salary (USD)"
        summary={salary ? `Salary: $${salary / 1000}k+` : 'Salary'}
        active={salary > 0}
        options={SALARIES}
        value={salary}
        onChange={(value) => onChange({ ...filters, minMonthlyUsd: value || null })}
      />
      {hide.includes('sources') ? null : (
        <FilterMenu multiple label="Sources" summary={filters.sources.length ? summarize('Sources', SOURCE_OPTIONS, filters.sources) : 'All Sources'} options={SOURCE_OPTIONS} value={filters.sources} onChange={(sources) => onChange({ ...filters, sources })} />
      )}
      <FilterMenu
        label="Sort by"
        align="end"
        summary={`Sort: ${SORT_LABELS[sort]}`}
        options={sortOptions.map((key) => ({ value: key, label: SORT_LABELS[key] }))}
        value={sort}
        onChange={onSortChange}
        className="ml-auto h-9 text-[13px]"
      />
    </div>
  )
}
