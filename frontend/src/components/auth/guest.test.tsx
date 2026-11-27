import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import type { Job } from '@/api/types'
import { RequireAuth } from '@/components/auth/RequireAuth'
import { Sidebar } from '@/components/layout/Sidebar'
import { Topbar } from '@/components/layout/Topbar'
import { TooltipProvider } from '@/components/ui/tooltip'
import OverviewPage from '@/pages/overview/OverviewPage'
import { useSession } from '@/stores/session'

// Behave like a production build: no dev bypass, so a visitor without a credential is a guest.
vi.mock('@/lib/env', () => ({ IS_DEV: false }))

const JOB: Job = {
  job_id: 7,
  title: 'Platform Engineer',
  company: 'Acme',
  location: 'Remote',
  source: 'greenhouse',
  source_name: 'Greenhouse',
  url: 'https://example.com/jobs/7',
  attribution: null,
  sources: [],
  published_at: '2026-11-20T10:00:00Z',
  first_seen_at: '2026-11-20T10:00:00Z',
  salary_text: null,
  extracted: null,
}

/** A JWT-shaped token whose payload names the account, as the API issues them (signature unchecked here). */
function tokenFor(email: string): string {
  const payload = btoa(JSON.stringify({ sub: 'user:1', email, exp: 4102444800 })).replace(/=+$/, '')
  return `eyJhbGciOiJIUzI1NiJ9.${payload}.signature`
}

function stubApi(): string[] {
  const urls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      urls.push(url)
      if (url.includes('/jobs')) return new Response(JSON.stringify({ limit: 20, offset: 0, total: 1, has_more: false, items: [JOB] }), { status: 200 })
      return new Response(JSON.stringify({ error: { code: 'unauthenticated', message: 'authentication required' } }), { status: 401 })
    }),
  )
  return urls
}

function renderApp(element: ReactNode, initial = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [
      { path: '/', element },
      { path: '/signin', element: <p>Sign-in page</p> },
      { path: '/signup', element: <p>Sign-up page</p> },
      { path: '/saved', element: <RequireAuth><p>Saved page</p></RequireAuth> },
    ],
    { initialEntries: [initial] },
  )
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return router
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  useSession.setState({ activeProfileId: null, token: null })
})

afterEach(() => vi.unstubAllGlobals())

describe('guest view', () => {
  it('shows public jobs, a Sign in button and the profile prompt, and asks for nothing personal', async () => {
    const urls = stubApi()
    renderApp(
      <>
        <Topbar onOpenMenu={() => undefined} />
        <Sidebar />
        <OverviewPage />
      </>,
    )

    expect(await screen.findByText('Platform Engineer')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Sign in' }).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('Create a profile to get matches')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()
    expect(urls.some((url) => url.includes('/jobs'))).toBe(true)
    expect(urls.filter((url) => /\/(profiles|saved-jobs|auth)/.test(url))).toEqual([])
  })

  it('sends a guest who wants to save a job to sign in, then back to the same page', async () => {
    const urls = stubApi()
    const router = renderApp(<OverviewPage />)

    await userEvent.setup().click(await screen.findByRole('button', { name: 'Save Platform Engineer' }))

    expect(router.state.location.pathname).toBe('/signin')
    expect(router.state.location.state).toMatchObject({ from: { pathname: '/' } })
    expect(urls.filter((url) => url.includes('/saved-jobs'))).toEqual([])
  })

  it('opens sign-in from the top bar with the page to return to', async () => {
    stubApi()
    const router = renderApp(<Topbar onOpenMenu={() => undefined} />)

    await userEvent.setup().click(screen.getByRole('button', { name: 'Sign in' }))

    expect(router.state.location.pathname).toBe('/signin')
    expect(router.state.location.state).toMatchObject({ from: { pathname: '/' } })
  })
})

describe('signed-in user', () => {
  it('sees the account in the sidebar and signs out, which forgets the token', async () => {
    stubApi()
    useSession.setState({ token: tokenFor('ada@example.com'), activeProfileId: 3 })
    window.sessionStorage.setItem('sanket.token', useSession.getState().token ?? '')
    const router = renderApp(<Sidebar />)

    expect(screen.getAllByText('ada@example.com').length).toBeGreaterThan(0)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Sign out' }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/signin'))
    expect(useSession.getState().token).toBeNull()
    expect(useSession.getState().activeProfileId).toBeNull()
    expect(window.sessionStorage.getItem('sanket.token')).toBeNull()
  })
})

describe('route guard', () => {
  it('sends a guest on a personal page to sign in and remembers the page', () => {
    const router = renderApp(<p>Overview</p>, '/saved')

    expect(screen.getByText('Sign-in page')).toBeInTheDocument()
    expect(router.state.location.state).toMatchObject({ from: { pathname: '/saved' } })
  })

  it('lets a signed-in user through', () => {
    useSession.setState({ token: tokenFor('ada@example.com') })
    renderApp(<p>Overview</p>, '/saved')

    expect(screen.getByText('Saved page')).toBeInTheDocument()
  })
})
