import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MotionConfig } from 'motion/react'
import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { ApiError, setUnauthorizedHandler } from '@/api/client'
import { RequireAuth } from '@/components/auth/RequireAuth'
import { AppShell } from '@/components/layout/AppShell'
import { LiveFeedController } from '@/features/live/LiveFeedController'
import { forgetSession, isAuthPath, SIGN_IN_PATH, SIGN_UP_PATH } from '@/lib/auth'
import { usePreferences } from '@/stores/preferences'

const OverviewPage = lazy(() => import('@/pages/overview/OverviewPage'))
const DiscoverPage = lazy(() => import('@/pages/discover/DiscoverPage'))
const JobDetailPage = lazy(() => import('@/pages/job/JobDetailPage'))
const LiveMatchesPage = lazy(() => import('@/pages/live/LiveMatchesPage'))
const SavedJobsPage = lazy(() => import('@/pages/saved/SavedJobsPage'))
const ProfilePage = lazy(() => import('@/pages/profile/ProfilePage'))
const SettingsPage = lazy(() => import('@/pages/settings/SettingsPage'))
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage'))
const SignInPage = lazy(() => import('@/pages/signin/SignInPage'))
const SignUpPage = lazy(() => import('@/pages/signup/SignUpPage'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      // Retrying cannot fix a refused credential or a request the API rejected; a 429 can wait.
      retry: (count, error) =>
        count < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500 && !error.isRateLimited),
      // After a 429, wait as long as the server asked (Retry-After); otherwise the usual backoff.
      retryDelay: (count, error) =>
        error instanceof ApiError && error.retryAfterMs !== null ? error.retryAfterMs : Math.min(1000 * 2 ** count, 30_000),
    },
  },
})

function guarded(element: ReactNode): ReactNode {
  return <RequireAuth>{element}</RequireAuth>
}

const router = createBrowserRouter([
  {
    path: SIGN_IN_PATH,
    element: (
      <Suspense fallback={null}>
        <SignInPage />
      </Suspense>
    ),
  },
  {
    path: SIGN_UP_PATH,
    element: (
      <Suspense fallback={null}>
        <SignUpPage />
      </Suspense>
    ),
  },
  {
    // Browsing is public; only the pages that hold an account's own data ask for sign-in.
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <OverviewPage /> },
      { path: 'discover', element: <DiscoverPage /> },
      { path: 'jobs/:jobId', element: <JobDetailPage /> },
      { path: 'live', element: guarded(<LiveMatchesPage />) },
      { path: 'saved', element: guarded(<SavedJobsPage />) },
      { path: 'profile', element: guarded(<ProfilePage />) },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

let redirecting = false

/** A 401 on a protected call means the credential is missing or no longer accepted: forget it and go to sign-in. */
function handleUnauthorized(): void {
  const { pathname, search, hash } = router.state.location
  // The sign-in and sign-up pages show their own errors, and parallel failing requests must redirect only once.
  if (isAuthPath(pathname) || redirecting) return
  redirecting = true
  forgetSession(queryClient)
  void router
    .navigate(SIGN_IN_PATH, { replace: true, state: { from: { pathname, search, hash } } })
    .finally(() => {
      redirecting = false
    })
}

setUnauthorizedHandler(handleUnauthorized)

export default function App() {
  const motion = usePreferences((s) => s.motion)
  return (
    <MotionConfig reducedMotion={motion === 'reduced' ? 'always' : 'user'}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        {/* Outside the router: the one live-feed connection outlives every route change. */}
        <LiveFeedController />
      </QueryClientProvider>
    </MotionConfig>
  )
}
