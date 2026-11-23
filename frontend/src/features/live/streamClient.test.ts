import { ApiError } from '@/api/client'
import type { MatchEvent } from '@/api/types'
import { MatchStreamClient, type EventSourceLike, type StreamState } from './streamClient'

class FakeSource implements EventSourceLike {
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  closed = false
  private listeners = new Map<string, (event: MessageEvent<string>) => void>()

  readonly url: string

  constructor(url: string) {
    this.url = url
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    this.listeners.set(type, listener)
  }
  close(): void {
    this.closed = true
  }
  open(): void {
    this.onopen?.(new Event('open'))
  }
  emit(event: Partial<MatchEvent>): void {
    this.listeners.get('match')?.(new MessageEvent('match', { data: JSON.stringify(event) }))
  }
  error(): void {
    this.onerror?.(new Event('error'))
  }
}

function match(id: number): Partial<MatchEvent> {
  return { id, job_id: id * 10, score: 0.9, status: 'active', components: {}, reactivated: false }
}

async function flush(): Promise<void> {
  await Promise.resolve()
  await Promise.resolve()
}

function setup(overrides: { resolveUrl?: (id: number | null) => Promise<string>; maxAttempts?: number } = {}) {
  const sources: FakeSource[] = []
  const states: StreamState[] = []
  const events: Partial<MatchEvent>[] = []
  const resolveUrl = vi.fn(overrides.resolveUrl ?? (async (id: number | null) => `/feed?last=${id ?? ''}`))
  const client = new MatchStreamClient({
    resolveUrl,
    onEvent: (event) => events.push(event),
    onState: (state) => states.push(state),
    createSource: (url) => {
      const source = new FakeSource(url)
      sources.push(source)
      return source
    },
    baseDelayMs: 1000,
    maxAttempts: overrides.maxAttempts ?? 3,
    isOnline: () => true,
    random: () => 0.5,
  })
  return { client, sources, states, events, resolveUrl, last: () => states[states.length - 1] }
}

describe('MatchStreamClient', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('reports connecting, then open once the source opens', async () => {
    const { client, sources, last } = setup()
    client.start()
    expect(last()?.status).toBe('connecting')
    await flush()
    sources[0]?.open()
    expect(last()?.status).toBe('open')
    client.stop()
  })

  it('delivers match events once each and tracks the last event id', async () => {
    const { client, sources, events, last } = setup()
    client.start()
    await flush()
    sources[0]?.open()
    sources[0]?.emit(match(4))
    sources[0]?.emit(match(4))
    sources[0]?.emit(match(7))
    expect(events.map((event) => event.id)).toEqual([4, 7])
    expect(last()?.lastEventId).toBe(7)
    client.stop()
  })

  it('ignores frames that are not match events', async () => {
    const { client, sources, events } = setup()
    client.start()
    await flush()
    sources[0]?.emit({ score: 1 } as Partial<MatchEvent>)
    expect(events).toHaveLength(0)
    client.stop()
  })

  it('reconnects with backoff and resumes from the last event id', async () => {
    const { client, sources, resolveUrl, last } = setup()
    client.start()
    await flush()
    sources[0]?.open()
    sources[0]?.emit(match(12))
    sources[0]?.error()
    expect(sources[0]?.closed).toBe(true)
    expect(last()?.status).toBe('reconnecting')
    expect(last()?.attempt).toBe(1)
    await vi.advanceTimersByTimeAsync(1000)
    expect(resolveUrl).toHaveBeenLastCalledWith(12)
    sources[1]?.open()
    expect(last()?.status).toBe('open')
    expect(last()?.attempt).toBe(0)
    client.stop()
  })

  it('gives up after the maximum number of attempts', async () => {
    const { client, sources, last } = setup({ maxAttempts: 2 })
    client.start()
    await flush()
    sources[0]?.error()
    await vi.advanceTimersByTimeAsync(1000)
    sources[1]?.error()
    await vi.advanceTimersByTimeAsync(2000)
    sources[2]?.error()
    expect(last()?.status).toBe('failed')
    expect(last()?.error).toMatch(/could not reconnect/i)
    client.stop()
  })

  it('fails at once without retrying when the credential is refused', async () => {
    const { client, sources, last } = setup({
      resolveUrl: async () => {
        throw new ApiError(401, 'unauthorized', 'authentication required')
      },
    })
    client.start()
    await flush()
    expect(last()?.status).toBe('failed')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(sources).toHaveLength(0)
    client.stop()
  })

  it('does not reconnect after stop', async () => {
    const { client, sources, last } = setup()
    client.start()
    await flush()
    sources[0]?.error()
    client.stop()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(sources).toHaveLength(1)
    expect(last()?.status).toBe('closed')
  })

  it('retryNow connects immediately after a failure', async () => {
    const { client, sources, last } = setup({ maxAttempts: 0 })
    client.start()
    await flush()
    sources[0]?.error()
    expect(last()?.status).toBe('failed')
    client.retryNow()
    await flush()
    sources[1]?.open()
    expect(last()?.status).toBe('open')
    client.stop()
  })
})
