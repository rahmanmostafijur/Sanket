import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { setUnauthorizedHandler } from '@/api/client'
import { useSession } from '@/stores/session'
import SignInPage from './SignInPage'

const EMAIL = 'ada@example.com'
const PASSWORD = 'correct horse battery'
const ISSUED = { access_token: 'header.payload.signature', token_type: 'bearer', expires_in: 3600, email: EMAIL }

function renderAt(entry: string | { pathname: string; state: unknown } = '/signin') {
  const router = createMemoryRouter(
    [
      { path: '/signin', element: <SignInPage /> },
      { path: '/signup', element: <p>Sign-up page</p> },
      { path: '/', element: <p>Overview page</p> },
      { path: '/saved', element: <p>Saved page</p> },
    ],
    { initialEntries: [entry] },
  )
  render(<RouterProvider router={router} />)
  return router
}

function respond(status: number, body: unknown, headers: Record<string, string> = {}): void {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status, headers })))
}

async function signIn(email: string, password: string): Promise<void> {
  const user = userEvent.setup()
  if (email) await user.type(screen.getByLabelText('Email'), email)
  if (password) await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: /sign in/i }))
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  useSession.setState({ activeProfileId: null, token: null })
})

afterEach(() => {
  vi.unstubAllGlobals()
  setUnauthorizedHandler(null)
})

describe('SignInPage', () => {
  it('posts the email and password, stores the token for this tab only and leaves the page', async () => {
    respond(200, ISSUED)
    const router = renderAt()

    await signIn(`  ${EMAIL} `, PASSWORD)

    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
    expect(useSession.getState().token).toBe(ISSUED.access_token)
    expect(window.sessionStorage.getItem('sanket.token')).toBe(ISSUED.access_token)
    expect(JSON.stringify(window.localStorage)).not.toContain(ISSUED.access_token)
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/auth/login')
    expect(JSON.parse(init.body as string)).toEqual({ email: EMAIL, password: PASSWORD })
  })

  it('returns to the page the user came from after signing in', async () => {
    respond(200, ISSUED)
    const router = renderAt({ pathname: '/signin', state: { from: { pathname: '/saved', search: '?page=2', hash: '' } } })

    await signIn(EMAIL, PASSWORD)

    await waitFor(() => expect(router.state.location.pathname).toBe('/saved'))
    expect(router.state.location.search).toBe('?page=2')
  })

  it('shows one generic message for a wrong email or password, without the global sign-out redirect', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    respond(401, { error: { code: 'unauthenticated', message: 'invalid email or password' } })
    const router = renderAt()

    await signIn(EMAIL, 'not the password')

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
    expect(handler).not.toHaveBeenCalled()
    expect(useSession.getState().token).toBeNull()
    expect(router.state.location.pathname).toBe('/signin')
    expect(screen.getByRole('button', { name: /sign in/i })).toBeEnabled()
  })

  it('says how long to wait when sign-in is rate limited', async () => {
    respond(429, { error: { code: 'rate_limited', message: 'too many requests, retry later' } }, { 'Retry-After': '42' })
    renderAt()

    await signIn(EMAIL, PASSWORD)

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts. Try again in 42 seconds.')
  })

  it('checks the fields first and sends nothing when they are not usable', async () => {
    respond(200, ISSUED)
    renderAt()

    await signIn('not-an-email', '')

    expect(await screen.findByText('Enter a valid email address, like name@example.com.')).toBeInTheDocument()
    expect(screen.getByText('Enter your password.')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('disables the button while the request is in flight', async () => {
    let release: (response: Response) => void = () => undefined
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { release = resolve })))
    renderAt()

    await signIn(EMAIL, PASSWORD)

    expect(screen.getByRole('button', { name: /signing in/i })).toBeDisabled()
    release(new Response(JSON.stringify(ISSUED), { status: 200 }))
    await waitFor(() => expect(useSession.getState().token).toBe(ISSUED.access_token))
  })

  it('links to sign-up and keeps the page to return to', async () => {
    const router = renderAt({ pathname: '/signin', state: { from: { pathname: '/saved', search: '', hash: '' } } })

    await userEvent.setup().click(screen.getByRole('link', { name: 'Create an account' }))

    expect(router.state.location.pathname).toBe('/signup')
    expect(router.state.location.state).toMatchObject({ from: { pathname: '/saved' } })
  })

  it('sends a user who is already signed in away from the page', async () => {
    useSession.setState({ token: ISSUED.access_token })
    const router = renderAt()

    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  })
})
