import { ApiError, apiRequest, buildUrl, errorMessage } from './client'
import { streamUrl } from './endpoints'

const config = { baseUrl: '/api', token: 'secret-key' }

function respond(status: number, body: unknown): void {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(body === undefined ? null : JSON.stringify(body), { status })))
}

afterEach(() => vi.unstubAllGlobals())

describe('buildUrl', () => {
  it('repeats list parameters and skips empty values', () => {
    expect(buildUrl('/api/', '/search', { q: 'python', work_mode: ['remote', 'hybrid'], company: '', limit: undefined })).toBe(
      '/api/search?q=python&work_mode=remote&work_mode=hybrid',
    )
  })
})

describe('apiRequest', () => {
  it('sends the bearer credential and parses JSON', async () => {
    respond(200, { items: [] })
    await expect(apiRequest(config, '/profiles')).resolves.toEqual({ items: [] })
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer secret-key')
  })

  it('turns the API error envelope into an ApiError', async () => {
    respond(404, { error: { code: 'not_found', message: 'profile not found', request_id: 'r1' } })
    const error = await apiRequest(config, '/profiles/9').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404, code: 'not_found', message: 'profile not found', requestId: 'r1' })
  })

  it('treats a proxy error without an envelope as the API being unreachable', async () => {
    respond(502, undefined)
    const error = (await apiRequest(config, '/healthz').catch((e: unknown) => e)) as ApiError
    expect(error.isUnavailable).toBe(true)
  })

  it('reports a network failure as unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const error = (await apiRequest(config, '/healthz').catch((e: unknown) => e)) as ApiError
    expect(error.code).toBe('network_error')
  })

  it('returns nothing for 204', async () => {
    respond(204, undefined)
    await expect(apiRequest(config, '/profiles/1', { method: 'DELETE' })).resolves.toBeUndefined()
  })
})

describe('errorMessage', () => {
  it('points at the credential settings for 401', () => {
    expect(errorMessage(new ApiError(401, 'unauthorized', 'nope'))).toMatch(/Settings, under Developers/)
  })
})

describe('streamUrl', () => {
  it('carries the stream token and resume point', () => {
    const token = { token: 't0k', expires_in: 60, path: '/profiles/3/matches/stream', query_parameter: 'stream_token' }
    expect(streamUrl(config, 3, { token, lastEventId: 41 })).toBe('/api/profiles/3/matches/stream?stream_token=t0k&last_event_id=41')
  })
  it('opens the feed path without a token when tokens are disabled', () => {
    expect(streamUrl(config, 3)).toBe('/api/profiles/3/matches/stream')
  })
})
