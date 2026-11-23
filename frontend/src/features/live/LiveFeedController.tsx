import { useEffect, useRef } from 'react'
import { ApiError, type ApiConfig } from '@/api/client'
import { mintStreamToken, streamUrl } from '@/api/endpoints'
import type { MatchEvent, StreamToken } from '@/api/types'
import { nextDemoEvent } from '@/data/demo'
import { useActiveProfile, useMatches } from '@/hooks/data'
import { percent } from '@/lib/format'
import { useJobRegistry } from '@/stores/jobRegistry'
import { useLiveFeed } from '@/stores/liveFeed'
import { usePreferences } from '@/stores/preferences'
import { useApiConfig, useSession } from '@/stores/session'
import { toast, useToasts } from '@/stores/toasts'
import { INITIAL_STREAM_STATE, MatchStreamClient } from './streamClient'

const TOKENS_DISABLED = 'stream tokens are not enabled'
const DEMO_FIRST_EVENT_MS = 6_000
const DEMO_INTERVAL_MS = 22_000

/** A stream token, or null when the server has tokens switched off (the dev bypass then admits). */
async function tokenFor(config: ApiConfig, profileId: number): Promise<StreamToken | null> {
  try {
    return await mintStreamToken(config, profileId)
  } catch (error: unknown) {
    if (error instanceof ApiError && error.status === 404 && error.message === TOKENS_DISABLED) return null
    throw error
  }
}

const TOAST_BATCH_MS = 600
let pendingToasts: MatchEvent[] = []
let toastTimer: ReturnType<typeof setTimeout> | null = null

/** Demo events belong to demo mode only; they must never surface while the API is the source. */
function isCurrentSource(simulated: boolean): boolean {
  return (useSession.getState().mode === 'demo') === simulated
}

function dropPendingToasts(): void {
  if (toastTimer !== null) clearTimeout(toastTimer)
  toastTimer = null
  pendingToasts = []
}

/** One toast per event, or one summary when a reconnect replays several at once. */
function flushToasts(simulated: boolean): void {
  const events = pendingToasts
  pendingToasts = []
  toastTimer = null
  if (!isCurrentSource(simulated)) return
  const prefix = simulated ? 'Demo · ' : ''
  const [first] = events
  if (!first) return
  if (events.length > 1) {
    toast({ tone: 'match', title: `${prefix}${events.length} new matches`, description: 'Open Live Matches to see them.', action: { label: 'View all', href: '/live' } })
    return
  }
  toast({
    tone: 'match',
    title: `${prefix}New match · ${percent(first.score)}%`,
    description: first.job ? `${first.job.title} at ${first.job.company}` : undefined,
    action: { label: 'View', href: `/jobs/${first.job_id}` },
  })
}

function announce(event: MatchEvent, simulated: boolean): void {
  if (!isCurrentSource(simulated)) return
  useJobRegistry.getState().remember(event.job ? [event.job] : [])
  useLiveFeed.getState().push(event)
  if (!usePreferences.getState().notifyOnMatch || !event.job) return
  pendingToasts = [...pendingToasts, event]
  if (toastTimer === null) toastTimer = setTimeout(() => flushToasts(simulated), TOAST_BATCH_MS)
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
    onEvent: (event) => announce(event, false),
    onState: (state) => useLiveFeed.getState().setStream(state, false),
  })
  useLiveFeed.getState().setRetry(() => client.retryNow())
  client.start()
  return () => client.stop()
}

/** Demo mode: a clearly simulated feed (the UI labels it "Demo stream", never "Live"). */
function startDemoFeed(profileId: number): () => void {
  const feed = useLiveFeed.getState()
  feed.setStream({ ...INITIAL_STREAM_STATE, status: 'open', connectedAt: Date.now() }, true)
  feed.setRetry(null)
  let sequence = 0
  const emit = () => {
    const event = nextDemoEvent(sequence, profileId)
    sequence += 1
    if (event) announce(event, true)
  }
  const first = setTimeout(emit, DEMO_FIRST_EVENT_MS)
  const interval = setInterval(emit, DEMO_INTERVAL_MS)
  return () => {
    clearTimeout(first)
    clearInterval(interval)
  }
}

/**
 * Owns the one match-feed connection of the app, for the active matching profile. Mounted once
 * above the router, so route changes never close or reopen it. Renders nothing.
 */
export function LiveFeedController(): null {
  const mode = useSession((s) => s.mode)
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
    const stop = mode === 'demo' ? startDemoFeed(profileId) : startApiFeed(config, profileId, () => highestId.current)
    return () => {
      stop()
      dropPendingToasts()
      useToasts.getState().dismissTone('match')
      useLiveFeed.getState().setRetry(null)
    }
  }, [mode, config, profileId])

  return null
}
