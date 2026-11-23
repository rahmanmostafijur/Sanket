import { useMemo } from 'react'
import type { Match } from '@/api/types'
import { useLiveFeed } from '@/stores/liveFeed'

export interface FeedEntry {
  match: Match
  /** When it arrived (live events) or was created (stored matches), ISO. */
  at: string
  /** Received over the live feed during this session. */
  isNew: boolean
}

/** Live events received this session first, then the most recent stored matches. */
export function useFeedEntries(matches: readonly Match[], limit: number): FeedEntry[] {
  const received = useLiveFeed((s) => s.received)
  return useMemo(() => {
    const live = received.map(({ event, receivedAt }) => ({ match: event as Match, at: new Date(receivedAt).toISOString(), isNew: true }))
    const liveIds = new Set(live.map((entry) => entry.match.id))
    const recent = [...matches]
      .filter((match) => !liveIds.has(match.id))
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
      .map((match) => ({ match, at: match.created_at, isNew: false }))
    return [...live, ...recent].slice(0, limit)
  }, [received, matches, limit])
}
