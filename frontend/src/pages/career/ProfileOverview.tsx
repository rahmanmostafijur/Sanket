import { CircleCheck, CircleDashed } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import type { Career, CareerSectionKey } from '@/api/types'
import { Card } from '@/components/ui/primitives'
import { CareerGate } from './CareerGate'
import { CvImport } from './CvImport'
import { useCvDraft } from './cvDraft'
import { proposalCounts } from './cvMerge'
import { DeriveMatching } from './DeriveMatching'
import { AVAILABILITY_OPTIONS, SECTION_META, formatYears, labelOf } from './labels'
import { useCvImport } from './useCvImport'

const SECTION_ORDER: readonly CareerSectionKey[] = ['personal', 'education', 'experience', 'skills', 'languages', 'certifications', 'projects']

function Completeness({ career }: { career: Career }) {
  const { percent, sections } = career.completeness
  const availability = labelOf(AVAILABILITY_OPTIONS, career.personal.availability)
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[16px] font-semibold text-fg">Profile completeness</h2>
        <p className="text-[22px] font-semibold tabular text-fg">{percent}%</p>
      </div>
      <div role="progressbar" aria-label="Profile completeness" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} className="mt-3 h-2 overflow-hidden rounded-full bg-elevated">
        <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${percent}%` }} />
      </div>
      <ul className="mt-5 grid gap-x-6 gap-y-2.5 sm:grid-cols-2">
        {SECTION_ORDER.map((key) => {
          const meta = SECTION_META[key]
          return (
            <li key={key} className="flex items-center gap-2.5 text-[14px]">
              {sections[key] ? <CircleCheck className="size-4 shrink-0 text-accent" /> : <CircleDashed className="size-4 shrink-0 text-subtle" />}
              {sections[key] ? (
                <span className="text-fg-2">{meta.label}</span>
              ) : (
                <Link to={meta.path} aria-label={`${meta.label} is empty. Add it`} className="font-medium text-fg hover:text-accent hover:underline">{meta.label}<span className="font-normal text-muted"> is empty. Add it</span></Link>
              )}
            </li>
          )
        })}
      </ul>
      <dl className="mt-5 flex flex-wrap gap-x-10 gap-y-3 border-t border-line pt-4 text-[14px]">
        <div>
          <dt className="text-[12.5px] text-subtle">Availability</dt>
          <dd className="mt-0.5 text-fg">
            {availability || 'Not set'} <Link to="/profile/personal" className="ml-1 text-[13px] text-accent hover:underline">Change in Personal</Link>
          </dd>
        </div>
        {career.years_of_experience !== null ? (
          <div>
            <dt className="text-[12.5px] text-subtle">Experience</dt>
            <dd className="mt-0.5 text-fg">About {formatYears(career.years_of_experience)}</dd>
          </div>
        ) : null}
      </dl>
    </Card>
  )
}

/** Where the last CV import put what it found: a link to each section that has something to review. */
function ImportResult({ career, imported }: { career: Career; imported: boolean }) {
  const { proposal } = useCvDraft()
  const counts = proposal ? proposalCounts(career, proposal) : {}
  const sections = SECTION_ORDER.filter((key) => counts[key])
  if (!sections.length) return imported ? <p role="status" className="text-[13.5px] text-muted">Nothing new was found in that CV.</p> : null
  return (
    <div role="status" className="rounded-xl border border-accent/30 bg-accent/[0.07] px-4 py-3 text-[13.5px] text-fg-2">
      <p>Your CV was read. Review what it filled in each section, then press Save there. Nothing is saved yet.</p>
      <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
        {sections.map((key) => (
          <li key={key}>
            <Link to={SECTION_META[key].path} className="font-medium text-accent hover:underline">{SECTION_META[key].label}</Link>
            <span className="text-muted"> ({counts[key]})</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Overview({ career }: { career: Career }) {
  const { receive } = useCvDraft()
  const [imported, setImported] = useState(false)
  const cv = useCvImport((proposal) => {
    receive(proposal)
    setImported(true)
  })
  return (
    <div className="space-y-5">
      <Completeness career={career} />
      <Card className="space-y-4 p-5 sm:p-6">
        <div>
          <h2 className="text-[16px] font-semibold text-fg">Import from CV</h2>
          <p className="mt-1 text-[13.5px] text-muted">Fill your sections from a CV to review. Nothing is saved until you press Save in a section.</p>
        </div>
        <CvImport cv={cv} />
        <ImportResult career={career} imported={imported} />
      </Card>
      <Card className="space-y-3 p-5 sm:p-6">
        <div>
          <h2 className="text-[16px] font-semibold text-fg">Find jobs that fit</h2>
          <p className="mt-1 text-[13.5px] text-muted">Start a matching profile from your experience and skills. You review it before anything is created.</p>
        </div>
        <DeriveMatching />
      </Card>
    </div>
  )
}

export function OverviewPage() {
  return <CareerGate>{(career) => <Overview career={career} />}</CareerGate>
}
