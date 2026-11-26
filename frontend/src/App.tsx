import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MotionConfig } from 'motion/react'
import { lazy, Suspense } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { ApiError, setUnauthorizedHandler } from '@/api/client'
import { RequireAuth } from '@/components/auth/RequireAuth'
import { AppShell } from '@/components/layout/AppShell'
import { LiveFeedController } from '@/features/live/LiveFeedController'
import { forgetSession } from '@/lib/auth'
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

const router = createBrowserRouter([
  {
    path: '/signin',
    element: (
      <Suspense fallback={null}>
        <SignInPage />
      </Suspense>
    ),
  },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <OverviewPage /> },
      { path: 'discover', element: <DiscoverPage /> },
      { path: 'jobs/:jobId', element: <JobDetailPage /> },
      { path: 'live', element: <LiveMatchesPage /> },
      { path: 'saved', element: <SavedJobsPage /> },
      { path: 'profile', element: <ProfilePage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

const SIGN_IN_PATH = '/signin'
let redirecting = false

/** A 401 means the credential is missing or no longer accepted: forget it and go to sign-in. */
function handleUnauthorized(): void {
  const { pathname, search, hash } = router.state.location
  // The sign-in page shows its own error, and parallel failing requests must redirect only once.
  if (pathname === SIGN_IN_PATH || redirecting) return
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
