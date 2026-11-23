import { CircleCheck, CircleHelp, CircleMinus, CircleX, Sparkles } from 'lucide-react'
import type { FilterState, Match } from '@/api/types'
import { Card } from '@/components/ui/primitives'
import { cautions, explainMatch, filterRows, scoreParts } from '@/features/match/explain'
import { cn } from '@/lib/cn'
import { percent } from '@/lib/format'
import { MatchBar } from './MatchVisuals'

const PART_COLORS = { cosine: 'var(--color-accent)', skills: 'var(--color-info)', title: 'var(--color-violet)' } as const

const FILTER_STYLE: Record<FilterState, { icon: typeof CircleCheck; className: string; text: string }> = {
  pass: { icon: CircleCheck, className: 'text-accent', text: 'Fits' },
  unknown: { icon: CircleHelp, className: 'text-amber', text: 'Not stated' },
  fail: { icon: CircleX, className: 'text-danger', text: 'Does not fit' },
  na: { icon: CircleMinus, className: 'text-subtle', text: 'Not filtered' },
}

function SkillGroup({ title, skills, tone }: { title: string; skills: readonly string[]; tone: 'strong' | 'bonus' | 'missing' }) {
  if (skills.length === 0) return null
  const style = {
    strong: 'border-accent/30 bg-accent/10 text-accent',
    bonus: 'border-info/30 bg-info/10 text-info',
    missing: 'border-danger/30 bg-danger/[0.08] text-danger',
  }[tone]
  return (
    <div>
      <p className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {skills.map((skill) => (
          <span key={skill} className={cn('inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-[12.5px] font-medium', style)}>
            {tone === 'missing' ? <CircleX className="size-3.5" /> : <CircleCheck className="size-3.5" />}
            {skill}
          </span>
        ))}
      </div>
    </div>
  )
}

/** "Your Match Breakdown": the real score parts, skills and filters of one match. */
export function MatchBreakdown({ match }: { match: Match }) {
  const { components } = match
  const parts = scoreParts(components)
  const filters = filterRows(components)
  const skills = components.skills
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-[16px] font-semibold text-fg">Your Match Breakdown</h2>
        <span className="text-[13px] text-muted">Score <span className="font-semibold text-fg tabular">{percent(match.score)}%</span></span>
      </div>
      {parts.length ? (
        <ul className="mt-5 space-y-4">
          {parts.map((part, index) => (
            <li key={part.key}>
              <div className="mb-2 flex items-center justify-between text-[13.5px]">
                <span className="text-fg-2">{part.label} <span className="text-subtle">· weight {Math.round(part.weight * 100)}%</span></span>
                <span className="font-medium text-fg tabular">{percent(part.value)}%</span>
              </div>
              <MatchBar value={part.value} color={PART_COLORS[part.key]} delay={0.1 + index * 0.08} label={part.label} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-[13px] text-muted">This match has no score breakdown recorded.</p>
      )}

      {skills ? (
        <div className="mt-6 space-y-4 border-t border-line pt-5">
          <SkillGroup title="Strong matches" skills={skills.required_hits} tone="strong" />
          <SkillGroup title="Bonus skills" skills={skills.preferred_hits} tone="bonus" />
          <SkillGroup title="Missing skills" skills={skills.required_missing} tone="missing" />
          {!skills.job_skills_known ? <p className="text-[12.5px] text-muted">The posting lists no skills to compare.</p> : null}
        </div>
      ) : null}

      {filters.length ? (
        <ul className="mt-5 grid grid-cols-1 gap-2 border-t border-line pt-5 sm:grid-cols-2">
          {filters.map((row) => {
            const style = FILTER_STYLE[row.state]
            const Icon = style.icon
            return (
              <li key={row.key} className="flex items-center gap-2 text-[13px]">
                <Icon className={cn('size-4 shrink-0', style.className)} />
                <span className="text-fg-2">{row.label}</span>
                <span className="ml-auto text-[12px] text-subtle">{style.text}</span>
              </li>
            )
          })}
        </ul>
      ) : null}
    </Card>
  )
}

export function MatchReasons({ match }: { match: Match }) {
  const reasons = explainMatch(match.components)
  const notes = cautions(match.components)
  return (
    <div className="space-y-5">
      <div>
        <h3 className="flex items-center gap-2 text-[15px] font-semibold text-fg"><Sparkles className="size-4 text-accent" />Why this job matches you</h3>
        {reasons.length ? (
          <ul className="mt-3 space-y-2.5">
            {reasons.map((reason) => (
              <li key={reason} className="flex gap-2.5 text-[14px] leading-relaxed text-fg-2">
                <CircleCheck className="mt-0.5 size-4 shrink-0 text-accent" />
                {reason}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[13.5px] text-muted">The matcher recorded no reasons for this match.</p>
        )}
      </div>
      {notes.length ? (
        <div>
          <h3 className="text-[14px] font-semibold text-fg">Worth checking</h3>
          <ul className="mt-2.5 space-y-2">
            {notes.map((note) => (
              <li key={note} className="flex gap-2.5 text-[13.5px] leading-relaxed text-muted">
                <CircleHelp className="mt-0.5 size-4 shrink-0 text-amber" />
                {note}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
