import type { QueryClient } from '@tanstack/react-query'
import { useSession } from '@/stores/session'

/** Everything that belongs to the signed-in user: the credential, cached API data, the chosen profile. */
export function forgetSession(queryClient: QueryClient): void {
  const { clearToken, setActiveProfileId } = useSession.getState()
  clearToken()
  queryClient.clear()
  setActiveProfileId(null)
}

/**
 * Sign-in is enforced only in production builds. A development build can talk to an API running
 * with AUTH_DEV_BYPASS and has no credential, so a signed-out developer keeps working there.
 */
export function shouldRequireSignIn(token: string | null, isDev: boolean): boolean {
  return !isDev && !token
}
