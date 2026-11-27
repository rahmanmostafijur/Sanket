import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { createMemoryRouter, Outlet, RouterProvider, type InitialEntry } from 'react-router'
import { Sidebar } from '@/components/layout/Sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'
import { profileRoute } from '@/pages/career/routes'

/** Renders the profile area at `entry`, with the sidebar beside it when the test needs to see it. */
export function renderProfileArea(entry: InitialEntry = '/profile', options: { sidebar?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const Shell = () => (
    <TooltipProvider>
      {options.sidebar ? <Sidebar /> : null}
      <Outlet />
    </TooltipProvider>
  )
  const router = createMemoryRouter([{ path: '/', element: <Shell />, children: [profileRoute()] }], { initialEntries: [entry] })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, client }
}

/** Loads the lazily imported pages up front, so the first test of a file is not charged for compiling them. */
export async function preloadProfileArea(): Promise<void> {
  await Promise.all([
    import('@/pages/career/ProfileOverview'),
    import('@/pages/career/SectionPages'),
    import('@/pages/profile/MatchingProfilesPage'),
  ])
}
