import type { ApiErrorBody } from './types'

export type ApiErrorDetail = NonNullable<ApiErrorBody['error']['details']>[number]

export interface ApiConfig {
  /** Where the API is mounted, e.g. "/api" behind the dev proxy. No trailing slash needed. */
  baseUrl: string
  /** Bearer credential (API key or JWT), or null to send none. */
  token: string | null
}

type QueryScalar = string | number | boolean
export type QueryValue = QueryScalar | QueryScalar[] | null | undefined

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  query?: Record<string, QueryValue>
  body?: unknown
  signal?: AbortSignal
  /** Whether a 401 runs the global unauthorized handler. Off for sign-in calls, where a 401 is a wrong password. */
  reportUnauthorized?: boolean
}

export type ApiErrorCode = 'network_error' | 'unreachable' | string

/** Any failed API call. `status` is 0 when the request never got an HTTP answer. */
export class ApiError extends Error {
  readonly status: number
  readonly code: ApiErrorCode
  readonly requestId: string | null
  /** How long the server asked us to wait (a 429's or 503's `Retry-After`), or null. */
  readonly retryAfterMs: number | null
  /** Which inputs a validation error (422) is about; empty otherwise. */
  readonly details: readonly ApiErrorDetail[]

  constructor(
    status: number,
    code: ApiErrorCode,
    message: string,
    requestId: string | null = null,
    retryAfterMs: number | null = null,
    details: readonly ApiErrorDetail[] = [],
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
    this.retryAfterMs = retryAfterMs
    this.details = details
  }

  get isRateLimited(): boolean {
    return this.status === 429
  }

  get isUnauthorized(): boolean {
    return this.status === 401 || this.status === 403
  }

  get isUnavailable(): boolean {
    return this.code === 'network_error' || this.code === 'unreachable'
  }
}

/** Absolute or root-relative URL with repeated keys for list values (`?a=1&a=2`). */
export function buildUrl(baseUrl: string, path: string, query?: Record<string, QueryValue>): string {
  const base = baseUrl.replace(/\/+$/, '')
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === '') continue
    const values = Array.isArray(value) ? value : [value]
    for (const item of values) params.append(key, String(item))
  }
  const search = params.toString()
  return `${base}${path}${search ? `?${search}` : ''}`
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false
  const error = (value as { error: unknown }).error
  return typeof error === 'object' && error !== null && 'message' in error
}

const MS_PER_SECOND = 1000

/** `Retry-After` as milliseconds: either delay-seconds or an HTTP date. Null when absent or invalid. */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  if (!value) return null
  const trimmed = value.trim()
  if (/^\d+(\.\d+)?$/.test(trimmed)) return Math.round(Number(trimmed) * MS_PER_SECOND)
  const date = Date.parse(trimmed)
  return Number.isNaN(date) ? null : Math.max(0, date - now)
}

async function errorFrom(response: Response): Promise<ApiError> {
  const body: unknown = await response.json().catch(() => null)
  const retryAfterMs = parseRetryAfter(response.headers.get('Retry-After'))
  if (isErrorBody(body)) {
    const { code, message, request_id: requestId, details } = body.error
    return new ApiError(response.status, code, message, requestId ?? null, retryAfterMs, Array.isArray(details) ? details : [])
  }
  if (response.status === 429) {
    return new ApiError(429, 'rate_limited', 'Too many requests. Please wait a moment.', null, retryAfterMs)
  }
  // No Sanket error envelope: a proxy answered because the API is down or not mounted there.
  if (response.status >= 500 || response.status === 404) {
    return new ApiError(response.status, 'unreachable', 'The Sanket API is not reachable at this address.')
  }
  return new ApiError(response.status, `http_${response.status}`, response.statusText || 'Request failed')
}

let unauthorizedHandler: (() => void) | null = null

/** Registers what to do when the API answers 401 (a missing or refused credential); null removes it. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

function notifyUnauthorized(): void {
  try {
    unauthorizedHandler?.()
  } catch {
    // A failing handler must never change what the caller sees: the request still rejects.
  }
}

export async function apiRequest<T>(
  config: ApiConfig,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (config.token) headers.Authorization = `Bearer ${config.token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  let response: Response
  try {
    response = await fetch(buildUrl(config.baseUrl, path, options.query), {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, 'network_error', 'Could not connect to the Sanket API.')
  }
  if (!response.ok) {
    const error = await errorFrom(response)
    if (response.status === 401 && options.reportUnauthorized !== false) notifyUnauthorized()
    throw error
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** A message fit for the UI from anything a query or mutation threw. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.isUnauthorized) {
      return import.meta.env.DEV
        ? 'Authentication required. Add an API key or token in Settings, under Developers.'
        : 'Sign in to your account to continue.'
    }
    return error.message
  }
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}
