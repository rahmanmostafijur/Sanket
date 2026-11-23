import type { MatchComponents } from '@/api/types'
import { cautions, explainMatch, filterRows, scoreParts } from './explain'

const components: MatchComponents = {
  cosine: { value: 0.81, part: 0.74, weight: 0.5, min: 0.5, ok: true },
  skills: {
    part: 0.66,
    weight: 0.35,
    required_hits: ['Python', 'FastAPI'],
    required_missing: ['PostgreSQL'],
    preferred_hits: ['Docker'],
    job_skills_known: true,
  },
  title: { part: 0.5, weight: 0.15, best: 'Backend Engineer' },
  filters: { seniority: 'pass', work_mode: 'pass', employment_type: 'na', country: 'unknown', required_skills: 'pass' },
  unknown_fields: ['country'],
  location_match: null,
  threshold: 0.6,
}

describe('match explanation', () => {
  it('lists the weighted score parts the scorer recorded', () => {
    expect(scoreParts(components).map((p) => [p.key, p.value, p.weight])).toEqual([
      ['cosine', 0.74, 0.5],
      ['skills', 0.66, 0.35],
      ['title', 0.5, 0.15],
    ])
  })

  it('leaves out parts that did not apply', () => {
    const parts = scoreParts({ ...components, title: { part: null, weight: 0.15, best: null } })
    expect(parts.map((p) => p.key)).toEqual(['cosine', 'skills'])
  })

  it('omits filters the profile left open', () => {
    expect(filterRows(components).map((row) => row.key)).toEqual(['seniority', 'work_mode', 'country', 'required_skills'])
  })

  it('explains matched skills, title, similarity and passed filters', () => {
    const reasons = explainMatch(components).join(' ')
    expect(reasons).toContain('Python and FastAPI')
    expect(reasons).toContain('Docker')
    expect(reasons).toContain('“Backend Engineer”')
    expect(reasons).toContain('81% similar')
    expect(reasons).toContain('seniority, work mode and required skills')
  })

  it('notes missing skills and filters the posting could not answer', () => {
    expect(cautions(components)).toEqual([
      'Not mentioned in the posting: PostgreSQL.',
      'The posting does not say its country, so those filters were not applied.',
    ])
  })

  it('says nothing it cannot back up when components are empty', () => {
    expect(explainMatch({})).toEqual([])
    expect(cautions({})).toEqual([])
    expect(scoreParts({})).toEqual([])
  })
})
