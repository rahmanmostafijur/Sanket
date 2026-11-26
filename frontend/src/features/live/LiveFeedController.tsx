import { useEffect, useRef } from 'react'
import { ApiError, type ApiConfig } from '@/api/client'
import { mintStreamToken, streamUrl } from '@/api/endpoints'
import type { MatchEvent, StreamToken } from '@/api/types'
import { useActiveProfile, useMatches } from '@/hooks/data'
import { percent } from '@/lib/format'
import { useJobRegistry } from '@/stores/jobRegistry'
import { useLiveFeed } from '@/stores/liveFeed'
import { usePreferences } from '@/stores/preferences'
import { useApiConfig } from '@/stores/session'
import { toast, useToasts } from '@/stores/toasts'
import { MatchStreamClient } from './streamClient'

const TOKENS_DISABLED = 'stream tokens are not enabled'

/** API addresses whose server answered that stream tokens are off; they are not asked again. */
const tokensDisabledAt = new Set<string>()

/**
 * A stream token, or null when none is needed or available: without a credential there is nothing
 * to exchange (the dev bypass admits the stream), and a server with tokens switched off says so
 * once with a 404, which is remembered for its address.
 */
async function tokenFor(config: ApiConfig, profileId: number): Promise<StreamToken | null> {
  if (!config.token || tokensDisabledAt.has(config.baseUrl)) return null
  try {
    return await mintStreamToken(config, profileId)
  } catch (error: unknown) {
    if (error instanceof ApiError && error.status === 404 && error.message === TOKENS_DISABLED) {
      tokensDisabledAt.add(config.baseUrl)
      return null
    }
    throw error
  }
}

const TOAST_BATCH_MS = 600
let pendingToasts: MatchEvent[] = []
let toastTimer: ReturnType<typeof setTimeout> | null = null

function dropPendingToasts(): void {
  if (toastTimer !== null) clearTimeout(toastTimer)
  toastTimer = null
  pendingToasts = []
}

/** One toast per event, or one summary when a reconnect replays several at once. */
function flushToasts(): void {
  const events = pendingToasts
  pendingToasts = []
  toastTimer = null
  const [first] = events
  if (!first) return
  if (events.length > 1) {
    toast({ tone: 'match', title: `${events.length} new matches`, description: 'Open Live Matches to see them.', action: { label: 'View all', href: '/live' } })
    return
  }
  toast({
    tone: 'match',
    title: `New match · ${percent(first.score)}%`,
    description: first.job ? `${first.job.title} at ${first.job.company}` : undefined,
    action: { label: 'View', href: `/jobs/${first.job_id}` },
  })
}

function announce(event: MatchEvent): void {
  useJobRegistry.getState().remember(event.job ? [event.job] : [])
  useLiveFeed.getState().push(event)
  if (!usePreferences.getState().notifyOnMatch || !event.job) return
  pendingToasts = [...pendingToasts, event]
  if (toastTimer === null) toastTimer = setTimeout(flushToasts, TOAST_BATCH_MS)
}

/**
 * `knownCursor` returns the highest match id already loaded. A stream opened without a cursor
 * only sends what happens after it opens, so without this, matches made between loading the list
 * and opening (or re-opening, before the first event) the stream would be missed.
 */
function startApiFeed(config: ApiConfig, profileId: number, knownCursor: () => number | null): () => void {
  const client = new MatchStreamClient({
    resolveUrl: async (lastEventId) =>
      streamUrl(config, profileId, { token: await tokenFor(config, profileId), lastEventId: lastEventId ?? knownCursor() }),
    onEvent: announce,
    onState: (state) => useLiveFeed.getState().setStream(state),
  })
  useLiveFeed.getState().setRetry(() => client.retryNow())
  client.start()
  return () => client.stop()
}

/**
 * Owns the one match-feed connection of the app, for the active matching profile. Mounted once
 * above the router, so route changes never close or reopen it. Renders nothing.
 */
export function LiveFeedController(): null {
  const config = useApiConfig()
  const { profile } = useActiveProfile()
  const profileId = profile?.id ?? null
  const { matches } = useMatches(profileId)
  const highestId = useRef<number | null>(null)

  useEffect(() => {
    const highest = matches.reduce((max, match) => Math.max(max, match.id), 0)
    highestId.current = highest > 0 ? highest : null
  }, [matches])

  useEffect(() => {
    useLiveFeed.getState().reset()
    if (profileId == null) return undefined
    const stop = startApiFeed(config, profileId, () => highestId.current)
    return () => {
      stop()
      dropPendingToasts()
      useToasts.getState().dismissTone('match')
      useLiveFeed.getState().setRetry(null)
    }
  }, [config, profileId])

  return null
}
