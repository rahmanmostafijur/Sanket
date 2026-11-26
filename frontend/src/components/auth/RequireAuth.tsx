import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { shouldRequireSignIn } from '@/lib/auth'
import { IS_DEV } from '@/lib/env'
import { useSession } from '@/stores/session'

interface RequireAuthProps {
  children: ReactNode
  /** Whether a missing credential forces sign-in. Defaults to production builds only. */
  enforce?: boolean
}

/** Sends a signed-out user to the sign-in page, remembering where they were going. */
export function RequireAuth({ children, enforce }: RequireAuthProps) {
  const token = useSession((s) => s.token)
  const location = useLocation()
  const required = enforce === undefined ? shouldRequireSignIn(token, IS_DEV) : enforce && !token
  if (required) return <Navigate to="/signin" replace state={{ from: location }} />
  return <>{children}</>
}
