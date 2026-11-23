import { create } from 'zustand'
import type { MatchEvent } from '@/api/types'
import { INITIAL_STREAM_STATE, type StreamState } from '@/features/live/streamClient'

const MAX_EVENTS = 100

export interface ReceivedEvent {
  event: MatchEvent
  /** When this browser received it (epoch ms). */
  receivedAt: number
}

interface LiveFeedState {
  /** Newest first. */
  received: ReceivedEvent[]
  unread: number
  stream: StreamState
  /** True while the feed is the demo simulator rather than the API stream. */
  simulated: boolean
  /** Reconnect now; set by the controller that owns the connection. */
  retry: (() => void) | null
  push: (event: MatchEvent) => void
  markRead: () => void
  setStream: (stream: StreamState, simulated: boolean) => void
  setRetry: (retry: (() => void) | null) => void
  reset: () => void
}

export const useLiveFeed = create<LiveFeedState>()((set, get) => ({
  received: [],
  unread: 0,
  stream: INITIAL_STREAM_STATE,
  simulated: false,
  retry: null,
  push: (event) => {
    const rest = get().received.filter((item) => item.event.id !== event.id)
    set({
      received: [{ event, receivedAt: Date.now() }, ...rest].slice(0, MAX_EVENTS),
      unread: get().unread + 1,
    })
  },
  markRead: () => set({ unread: 0 }),
  setStream: (stream, simulated) => set({ stream, simulated }),
  setRetry: (retry) => set({ retry }),
  reset: () => set({ received: [], unread: 0, stream: INITIAL_STREAM_STATE, simulated: false }),
}))
