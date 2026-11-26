import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { useSession } from '@/stores/session'
import SignInPage from './SignInPage'

const CREDENTIAL = 'sk-test-credential-123'

function renderAt(entry: string | { pathname: string; state: unknown } = '/signin') {
  const router = createMemoryRouter(
    [
      { path: '/signin', element: <SignInPage /> },
      { path: '/', element: <p>Overview page</p> },
      { path: '/saved', element: <p>Saved page</p> },
    ],
    { initialEntries: [entry] },
  )
  render(<RouterProvider router={router} />)
  return router
}

function respond(status: number, body: unknown): void {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status })))
}

async function submit(value: string): Promise<void> {
  const user = userEvent.setup()
  if (value) await user.type(screen.getByLabelText('Access key or token'), value)
  await user.click(screen.getByRole('button', { name: /sign in/i }))
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  useSession.setState({ activeProfileId: null, token: null })
})

afterEach(() => vi.unstubAllGlobals())

describe('SignInPage', () => {
  it('shows an inline error and stores nothing when the credential is refused', async () => {
    respond(401, { error: { code: 'unauthorized', message: 'invalid credential' } })
    const router = renderAt()

    await submit(CREDENTIAL)

    expect(await screen.findByRole('alert')).toHaveTextContent('That key or token was not accepted.')
    expect(useSession.getState().token).toBeNull()
    expect(window.sessionStorage.getItem('sanket.token')).toBeNull()
    expect(router.state.location.pathname).toBe('/signin')
  })

  it('says so, and stores nothing, when the credential is valid but has no access', async () => {
    respond(403, { error: { code: 'forbidden', message: 'missing scope' } })
    renderAt()

    await submit(CREDENTIAL)

    expect(await screen.findByRole('alert')).toHaveTextContent('This credential is valid but does not have access.')
    expect(useSession.getState().token).toBeNull()
  })

  it('stores the credential and leaves the page when the API accepts it', async () => {
    respond(200, { items: [] })
    const router = renderAt()

    await submit(`  ${CREDENTIAL}  `)

    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
    expect(await screen.findByText('Overview page')).toBeInTheDocument()
    expect(useSession.getState().token).toBe(CREDENTIAL)
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/profiles')
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${CREDENTIAL}`)
  })

  it('returns to the page the user came from after signing in', async () => {
    respond(200, { items: [] })
    const router = renderAt({ pathname: '/signin', state: { from: { pathname: '/saved', search: '?page=2', hash: '' } } })

    await submit(CREDENTIAL)

    await waitFor(() => expect(router.state.location.pathname).toBe('/saved'))
    expect(router.state.location.search).toBe('?page=2')
  })

  it('asks for a value and sends no request when the field is empty', async () => {
    respond(200, { items: [] })
    renderAt()

    await submit('')

    expect(await screen.findByRole('alert')).toHaveTextContent('Enter your access key or token.')
    expect(fetch).not.toHaveBeenCalled()
    expect(useSession.getState().token).toBeNull()
  })

  it('sends a user who is already signed in away from the page', async () => {
    useSession.setState({ token: CREDENTIAL })
    const router = renderAt()

    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  })
})
