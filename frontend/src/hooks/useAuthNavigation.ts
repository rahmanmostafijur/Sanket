import { useLocation, useNavigate, type Location } from 'react-router'
import { SIGN_IN_PATH, SIGN_UP_PATH } from '@/lib/auth'

/** The state the sign-in and sign-up pages read to send the user back where they were. */
export function returnState(location: Pick<Location, 'pathname' | 'search' | 'hash'>): {
  from: { pathname: string; search: string; hash: string }
} {
  return { from: { pathname: location.pathname, search: location.search, hash: location.hash } }
}

/** Opens the sign-in or sign-up page, remembering the current page to come back to. */
export function useAuthNavigation(): { signIn: () => void; signUp: () => void } {
  const navigate = useNavigate()
  const location = useLocation()
  return {
    signIn: () => void navigate(SIGN_IN_PATH, { state: returnState(location) }),
    signUp: () => void navigate(SIGN_UP_PATH, { state: returnState(location) }),
  }
}
