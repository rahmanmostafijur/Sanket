import type { Career, CareerListKey, CareerSectionKey, Me } from '@/api/types'

export interface Call {
  method: string
  path: string
  init: RequestInit
}

export interface Reply {
  status: number
  body?: unknown
  headers?: Record<string, string>
}

export function reply(status: number, body?: unknown, headers: Record<string, string> = {}): Reply {
  return { status, body, headers }
}

export const NOT_FOUND = reply(404, { error: { code: 'not_found', message: 'not found' } })
export const NO_ACCOUNT = reply(404, { error: { code: 'not_found', message: 'this credential has no account' } })

export const LIST_KEYS: readonly CareerListKey[] = ['education', 'experience', 'skills', 'languages', 'certifications', 'projects']

const SECTIONS: readonly CareerSectionKey[] = ['personal', ...LIST_KEYS]

/** The career profile of a brand-new account: every value empty. */
export function emptyCareer(): Career {
  return {
    personal: { full_name: '', headline: '', summary: '', country: '', city: '', github_url: '', linkedin_url: '', portfolio_url: '', availability: null },
    education: [],
    experience: [],
    skills: [],
    languages: [],
    certifications: [],
    projects: [],
    completeness: { percent: 0, sections: Object.fromEntries(SECTIONS.map((key) => [key, false])) as Career['completeness']['sections'], missing: [...SECTIONS] },
    years_of_experience: null,
  }
}

/** Fills in the completeness figure the way the API does, from what the profile holds. */
export function withCompleteness(career: Career): Career {
  const p = career.personal
  const sections = {
    personal: Boolean(p.full_name || p.headline || p.summary),
    education: career.education.length > 0,
    experience: career.experience.length > 0,
    skills: career.skills.length > 0,
    languages: career.languages.length > 0,
    certifications: career.certifications.length > 0,
    projects: career.projects.length > 0,
  }
  const done = SECTIONS.filter((key) => sections[key]).length
  return { ...career, completeness: { percent: Math.round((100 * done) / SECTIONS.length), sections, missing: SECTIONS.filter((key) => !sections[key]) } }
}

export type Route = Reply | ((call: Call) => Reply | Promise<Reply>)

export interface Backend {
  calls: Call[]
  /** The career profile as the fake server holds it now. */
  career: () => Career
  me: () => Me
}

interface BackendOptions {
  career?: Partial<Career>
  me?: Partial<Me>
  /** Answers by "METHOD /path"; these win over the built-in career and account routes. */
  routes?: Record<string, Route>
}

/**
 * Stubs fetch with a small stateful fake of the career API: what is saved is what the next read
 * returns, so a section's read view can be checked after Save. Anything not answered is a 404.
 */
export function stubBackend(options: BackendOptions = {}): Backend {
  let career = withCompleteness({ ...emptyCareer(), ...options.career })
  let me: Me = { email: 'ada@example.com', full_name: career.personal.full_name, headline: career.personal.headline, ...options.me }
  const calls: Call[] = []
  let nextId = 100
  const withIds = (items: unknown[]) => items.map((item) => ({ ...(item as object), id: nextId++ }))

  const builtIn = (call: Call): Reply | null => {
    const { method, path } = call
    const body = typeof call.init.body === 'string' ? (JSON.parse(call.init.body) as Record<string, unknown>) : null
    if (method === 'GET' && path === '/me') return reply(200, me)
    if (method === 'GET' && path === '/career') return reply(200, career)
    if (method === 'PUT' && path === '/career/personal' && body) {
      career = withCompleteness({ ...career, personal: body as unknown as Career['personal'] })
      me = { ...me, full_name: career.personal.full_name, headline: career.personal.headline }
      return reply(200, career.personal)
    }
    const list = /^\/career\/(\w+)$/.exec(path)?.[1] as CareerListKey | undefined
    if (method === 'PUT' && list && LIST_KEYS.includes(list) && body) {
      const items = withIds(body.items as unknown[])
      career = withCompleteness({ ...career, [list]: items })
      return reply(200, { items })
    }
    return null
  }

  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const call: Call = { method: init.method ?? 'GET', path: String(input).replace(/^\/api/, ''), init }
      calls.push(call)
      const route = options.routes?.[`${call.method} ${call.path}`]
      const answer = route === undefined ? (builtIn(call) ?? NOT_FOUND) : typeof route === 'function' ? await route(call) : route
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), { status: answer.status, headers: answer.headers })
    }),
  )
  return { calls, career: () => career, me: () => me }
}

export const named = (calls: Call[], method: string, path: string): Call[] => calls.filter((call) => call.method === method && call.path === path)

/** The one call of this kind, or an error when there were none or several. */
export function only(calls: Call[], method: string, path: string): Call {
  const [call, ...rest] = named(calls, method, path)
  if (!call || rest.length) throw new Error(`expected exactly one ${method} ${path}, got ${named(calls, method, path).length}`)
  return call
}

export function bodyOf(call: Call): unknown {
  return JSON.parse(call.init.body as string)
}

/** A token that reads as an account's, for the sidebar. */
export function accountToken(email = 'ada@example.com'): string {
  const payload = btoa(JSON.stringify({ sub: 'user:1', email, exp: 4102444800 })).replace(/=+$/, '')
  return `eyJhbGciOiJIUzI1NiJ9.${payload}.signature`
}

/** jsdom has no ResizeObserver (the switches measure with it) and no scrollIntoView (moving to a field calls it). */
export function stubBrowserGaps(): { scrollIntoView: ReturnType<typeof vi.fn> } {
  globalThis.ResizeObserver ??= class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  const scrollIntoView = vi.fn()
  Element.prototype.scrollIntoView = scrollIntoView
  return { scrollIntoView }
}
