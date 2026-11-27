import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useSession } from '@/stores/session'
import { Sidebar } from './Sidebar'

function tokenFor(email: string): string {
  const payload = btoa(JSON.stringify({ sub: 'user:1', email, exp: 4102444800 })).replace(/=+$/, '')
  return `eyJhbGciOiJIUzI1NiJ9.${payload}.signature`
}

const ME = { email: 'ada@example.com', full_name: '', headline: '' }

function stubMe(status: number, body: unknown): void {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status })))
}

function renderSidebar(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter([{ path: '/', element: <Sidebar /> }])
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  useSession.setState({ activeProfileId: null, token: null })
})

afterEach(() => vi.unstubAllGlobals())

describe('sidebar user row', () => {
  it('shows only the full name once the account has one', async () => {
    stubMe(200, { ...ME, full_name: 'Ada Example' })
    useSession.setState({ token: tokenFor(ME.email) })
    renderSidebar()

    expect(await screen.findByText('Ada Example')).toBeInTheDocument()
    expect(screen.queryByText(ME.email)).not.toBeInTheDocument()
    expect(screen.queryByText(/signed in with/i)).not.toBeInTheDocument()
  })

  it('shows only the email when the account has no full name', async () => {
    stubMe(200, ME)
    useSession.setState({ token: tokenFor(ME.email) })
    renderSidebar()

    expect(await screen.findByText(ME.email)).toBeInTheDocument()
    expect(screen.getAllByText(ME.email)).toHaveLength(1)
    expect(screen.queryByText(/signed in with/i)).not.toBeInTheDocument()
  })

  it('shows "API key" and no key digits when the credential is not an account', async () => {
    stubMe(404, { error: { code: 'not_found', message: 'not an account' } })
    useSession.setState({ token: 'sk_live_1234567890' })
    renderSidebar()

    expect(await screen.findByText('API key')).toBeInTheDocument()
    expect(screen.queryByText(/7890|key ending/i)).not.toBeInTheDocument()
  })
})
