import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MotionConfig } from 'motion/react'
import { lazy } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { ApiError } from '@/api/client'
import { AppShell } from '@/components/layout/AppShell'
import { usePreferences } from '@/stores/preferences'

const OverviewPage = lazy(() => import('@/pages/overview/OverviewPage'))
const DiscoverPage = lazy(() => import('@/pages/discover/DiscoverPage'))
const JobDetailPage = lazy(() => import('@/pages/job/JobDetailPage'))
const LiveMatchesPage = lazy(() => import('@/pages/live/LiveMatchesPage'))
const SavedJobsPage = lazy(() => import('@/pages/saved/SavedJobsPage'))
const ProfilePage = lazy(() => import('@/pages/profile/ProfilePage'))
const SalaryInsightsPage = lazy(() => import('@/pages/salary/SalaryInsightsPage'))
const IntegrationsPage = lazy(() => import('@/pages/integrations/IntegrationsPage'))
const SettingsPage = lazy(() => import('@/pages/settings/SettingsPage'))
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      // Retrying cannot fix a refused credential or a request the API rejected.
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
  },
})

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <OverviewPage /> },
      { path: 'discover', element: <DiscoverPage /> },
      { path: 'jobs/:jobId', element: <JobDetailPage /> },
      { path: 'live', element: <LiveMatchesPage /> },
      { path: 'saved', element: <SavedJobsPage /> },
      { path: 'profile', element: <ProfilePage /> },
      { path: 'salary', element: <SalaryInsightsPage /> },
      { path: 'integrations', element: <IntegrationsPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

export default function App() {
  const motion = usePreferences((s) => s.motion)
  return (
    <MotionConfig reducedMotion={motion === 'reduced' ? 'always' : 'user'}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MotionConfig>
  )
}
