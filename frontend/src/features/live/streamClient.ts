import { ApiError } from '@/api/client'
import type { MatchEvent } from '@/api/types'

/**
 * A resilient client for the match feed (GET /profiles/{id}/matches/stream, Server-Sent Events).
 *
 * Native EventSource reconnects by itself, but always to the URL it was opened with, and the
 * stream token in that URL expires after about a minute. So on any error this client closes
 * the source and reconnects itself with backoff: it asks `resolveUrl` for a fresh URL (a new
 * token) carrying the last event id it saw, which makes the server replay what was missed.
 */

export type StreamStatus =
  | 'idle'
  | 'connecting'
  | 'open'
  | 'reconnecting'
  | 'offline'
  | 'failed'
  | 'closed'

export interface StreamState {
  status: StreamStatus
  /** Failed attempts since the last successful open. */
  attempt: number
  lastEventId: number | null
  error: string | null
  connectedAt: number | null
  /** When the next reconnect is scheduled (epoch ms), while reconnecting. */
  retryAt: number | null
}

export interface EventSourceLike {
  onopen: ((event: Event) => void) | null
  onerror: ((event: Event) => void) | null
  addEventListener: (type: string, listener: (event: MessageEvent<string>) => void) => void
  close: () => void
}

export interface StreamClientOptions {
  resolveUrl: (lastEventId: number | null) => Promise<string>
  onEvent: (event: MatchEvent) => void
  onState: (state: StreamState) => void
  createSource?: (url: string) => EventSourceLike
  baseDelayMs?: number
  maxDelayMs?: number
  maxAttempts?: number
  isOnline?: () => boolean
  random?: () => number
}

export const INITIAL_STREAM_STATE: StreamState = {
  status: 'idle',
  attempt: 0,
  lastEventId: null,
  error: null,
  connectedAt: null,
  retryAt: null,
}

const EVENT_NAME = 'match'
const MAX_SEEN_IDS = 1000

function isMatchEvent(value: unknown): value is MatchEvent {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Partial<MatchEvent>
  return typeof candidate.id === 'number' && typeof candidate.score === 'number'
}

function defaultSource(url: string): EventSourceLike {
  return new EventSource(url) as unknown as EventSourceLike
}

function defaultOnline(): boolean {
  return typeof navigator === 'undefined' || navigator.onLine !== false
}

export class MatchStreamClient {
  private readonly options: Required<Omit<StreamClientOptions, 'resolveUrl' | 'onEvent' | 'onState'>> &
    Pick<StreamClientOptions, 'resolveUrl' | 'onEvent' | 'onState'>
  private state: StreamState = INITIAL_STREAM_STATE
  private source: EventSourceLike | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private running = false
  private generation = 0
  private readonly seen = new Set<string>()

  constructor(options: StreamClientOptions) {
    this.options = {
      createSource: defaultSource,
      baseDelayMs: 1000,
      maxDelayMs: 30_000,
      maxAttempts: 8,
      isOnline: defaultOnline,
      random: Math.random,
      ...options,
    }
  }

  get snapshot(): StreamState {
    return this.state
  }

  start(): void {
    if (this.running) return
    this.running = true
    if (typeof window !== 'undefined') window.addEventListener('online', this.handleOnline)
    void this.connect()
  }

  stop(): void {
    this.running = false
    this.generation += 1
    this.teardown()
    if (typeof window !== 'undefined') window.removeEventListener('online', this.handleOnline)
    this.update({ status: 'closed', retryAt: null })
  }

  /** Reconnect now (after `failed`, or to skip a scheduled backoff). */
  retryNow(): void {
    if (!this.running) {
      this.start()
      return
    }
    this.teardown()
    this.update({ attempt: 0, error: null })
    void this.connect()
  }

  private readonly handleOnline = (): void => {
    if (this.running && this.state.status === 'offline') void this.connect()
  }

  private update(patch: Partial<StreamState>): void {
    this.state = { ...this.state, ...patch }
    this.options.onState(this.state)
  }

  private teardown(): void {
    if (this.timer !== null) clearTimeout(this.timer)
    this.timer = null
    this.source?.close()
    this.source = null
  }

  private async connect(): Promise<void> {
    const generation = ++this.generation
    this.teardown()
    this.update({ status: this.state.attempt === 0 ? 'connecting' : 'reconnecting', retryAt: null })
    let url: string
    try {
      url = await this.options.resolveUrl(this.state.lastEventId)
    } catch (error: unknown) {
      if (generation === this.generation) this.fail(error)
      return
    }
    if (generation !== this.generation || !this.running) return
    const source = this.options.createSource(url)
    this.source = source
    source.onopen = () => {
      if (generation !== this.generation) return
      this.update({ status: 'open', attempt: 0, error: null, connectedAt: Date.now() })
    }
    source.addEventListener(EVENT_NAME, (event) => {
      if (generation === this.generation) this.receive(event)
    })
    source.onerror = () => {
      if (generation !== this.generation) return
      source.close()
      this.fail(null)
    }
  }

  private receive(event: MessageEvent<string>): void {
    let data: unknown
    try {
      data = JSON.parse(event.data)
    } catch {
      return
    }
    if (!isMatchEvent(data)) return
    // A reactivated or rescored match comes back under the same id with a newer updated_at.
    const key = `${data.id}:${data.updated_at}`
    if (this.seen.has(key)) return
    this.remember(key)
    const lastEventId = Math.max(this.state.lastEventId ?? 0, data.id)
    if (lastEventId !== this.state.lastEventId) this.update({ lastEventId })
    this.options.onEvent(data)
  }

  private remember(id: string): void {
    this.seen.add(id)
    if (this.seen.size <= MAX_SEEN_IDS) return
    const oldest = this.seen.values().next().value
    if (oldest !== undefined) this.seen.delete(oldest)
  }

  private fail(error: unknown): void {
    if (!this.running) return
    this.source = null
    const attempt = this.state.attempt + 1
    if (error instanceof ApiError && (error.isUnauthorized || error.status === 404)) {
      this.update({ status: 'failed', attempt, error: error.message })
      return
    }
    const message = error instanceof Error ? error.message : 'The live connection was interrupted.'
    if (attempt > this.options.maxAttempts) {
      this.update({ status: 'failed', attempt, error: 'Could not reconnect to the live feed.' })
      return
    }
    const { baseDelayMs, maxDelayMs, random } = this.options
    const backoff = Math.min(maxDelayMs, baseDelayMs * 2 ** (attempt - 1)) * (0.8 + random() * 0.4)
    // A 429 says how long to wait; never come back sooner than that.
    const delay = Math.max(backoff, error instanceof ApiError ? (error.retryAfterMs ?? 0) : 0)
    // navigator.onLine can be wrong (VPNs, containers), so keep the timer and use it for the label only.
    const offline = !this.options.isOnline()
    this.update({ status: offline ? 'offline' : 'reconnecting', attempt, error: offline ? 'You are offline.' : message, retryAt: Date.now() + delay })
    this.timer = setTimeout(() => void this.connect(), delay)
  }
}
