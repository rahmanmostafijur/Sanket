export interface Identity {
  name: string
  detail: string
  initials: string
  kind: 'jwt' | 'api_key' | 'none'
}

/** Seconds-since-epoch `exp` of a JWT, for display only; null for API keys or no expiry. */
export function jwtExpiry(token: string): Date | null {
  const exp = decodeJwtPayload(token)?.exp
  return typeof exp === 'number' ? new Date(exp * 1000) : null
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split('.')
  if (parts.length !== 3 || !parts[1]) return null
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const json = decodeURIComponent(
      Array.from(atob(base64), (char) => `%${char.charCodeAt(0).toString(16).padStart(2, '0')}`).join(''),
    )
    const payload: unknown = JSON.parse(json)
    return typeof payload === 'object' && payload !== null ? (payload as Record<string, unknown>) : null
  } catch {
    return null
  }
}

function text(payload: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = payload[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return null
}

function initialsOf(name: string): string {
  const words = name.split(/[\s@._-]+/).filter(Boolean)
  return ((words[0]?.[0] ?? '?') + (words[1]?.[0] ?? '')).toUpperCase()
}

/**
 * Who to show as signed in. The API has no "me" endpoint: a JWT's own claims are read for
 * display only (never trusted for anything), an API key is shown as such.
 */
export function describeIdentity(token: string | null): Identity {
  if (!token) return { name: 'Not signed in', detail: 'No credential set', initials: '?', kind: 'none' }
  const payload = decodeJwtPayload(token)
  if (payload) {
    const name = text(payload, 'name', 'preferred_username', 'nickname', 'email', 'sub') ?? 'Signed in'
    const detail = text(payload, 'email', 'sub') ?? 'JWT'
    return { name, detail: detail === name ? 'Signed in with JWT' : detail, initials: initialsOf(name), kind: 'jwt' }
  }
  return { name: 'API key', detail: `Key ending ${token.slice(-4)}`, initials: 'AK', kind: 'api_key' }
}

/** First name for the greeting, or null when there is no person to greet. */
export function firstName(identity: Identity): string | null {
  if (identity.kind === 'jwt') {
    const first = identity.name.split(/\s+/)[0]
    return first && !first.includes('@') ? first : null
  }
  return null
}
