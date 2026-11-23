/**
 * The job sources the backend ingests, mirroring SOURCE_INFO in
 * backend/src/sanket/search/attribution.py. Ids are what the `source` search filter takes.
 */
export interface SourceMeta {
  id: string
  name: string
  /** Dot colour used to tell sources apart in lists. */
  color: string
}

export const SOURCES: readonly SourceMeta[] = [
  { id: 'remoteok', name: 'Remote OK', color: '#8aa8ff' },
  { id: 'remotive', name: 'Remotive', color: '#5eead4' },
  { id: 'weworkremotely', name: 'We Work Remotely', color: '#f5c451' },
  { id: 'himalayas', name: 'Himalayas', color: '#a98bff' },
  { id: 'jobicy', name: 'Jobicy', color: '#f0abfc' },
  { id: 'greenhouse', name: 'Greenhouse', color: '#b8f36b' },
  { id: 'lever', name: 'Lever', color: '#fb923c' },
  { id: 'ashby', name: 'Ashby', color: '#93c5fd' },
  { id: 'usajobs', name: 'USAJOBS', color: '#fca5a5' },
  { id: 'jobtech_se', name: 'JobTech Sweden', color: '#67e8f9' },
]

const BY_ID = new Map(SOURCES.map((source) => [source.id, source]))
const FALLBACK_COLOR = '#94a3b8'

export function sourceMeta(id: string | null | undefined): SourceMeta | null {
  return id ? (BY_ID.get(id) ?? { id, name: id, color: FALLBACK_COLOR }) : null
}
