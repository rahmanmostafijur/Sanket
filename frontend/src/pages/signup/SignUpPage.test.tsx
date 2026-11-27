import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { useSession } from '@/stores/session'
import SignUpPage from './SignUpPage'

const EMAIL = 'grace@example.com'
const PASSWORD = 'a long enough passphrase'
const ISSUED = { access_token: 'header.payload.signature', token_type: 'bearer', expires_in: 3600, email: EMAIL }

function renderAt(entry: string | { pathname: string; state: unknown } = '/signup') {
  const router = createMemoryRouter(
    [
      { path: '/signup', element: <SignUpPage /> },
      { path: '/signin', element: <p>Sign-in page</p> },
      { path: '/profile', element: <p>Profile page</p> },
      { path: '/jobs/:jobId', element: <p>Job page</p> },
    ],
    { initialEntries: [entry] },
  )
  render(<RouterProvider router={router} />)
  return router
}

function respond(status: number, body: unknown): void {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status })))
}

async function fill(email: string, password: string, confirm: string): Promise<void> {
  const user = userEvent.setup()
  if (email) await user.type(screen.getByLabelText('Email'), email)
  if (password) await user.type(screen.getByLabelText('Password'), password)
  if (confirm) await user.type(screen.getByLabelText('Confirm password'), confirm)
  await user.click(screen.getByRole('button', { name: /create account/i }))
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  useSession.setState({ activeProfileId: null, token: null })
})

afterEach(() => vi.unstubAllGlobals())

describe('SignUpPage', () => {
  it('shows each problem next to its field and sends nothing', async () => {
    respond(201, ISSUED)
    renderAt()

    await fill('grace@', 'short', 'short')

    expect(await screen.findByText('Enter a valid email address, like name@example.com.')).toBeInTheDocument()
    expect(screen.getByText('Use at least 12 characters.')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('asks for matching passwords and clears the message once they match', async () => {
    respond(201, ISSUED)
    renderAt()

    await fill(EMAIL, PASSWORD, `${PASSWORD}!`)

    expect(await screen.findByText('The passwords do not match.')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
    await userEvent.setup().type(screen.getByLabelText('Confirm password'), '{Backspace}')
    expect(screen.queryByText('The passwords do not match.')).not.toBeInTheDocument()
  })

  it('creates the account, signs the user in and opens the profile page', async () => {
    respond(201, ISSUED)
    const router = renderAt()

    await fill(EMAIL, PASSWORD, PASSWORD)

    await waitFor(() => expect(router.state.location.pathname).toBe('/profile'))
    expect(useSession.getState().token).toBe(ISSUED.access_token)
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/auth/signup')
    expect(JSON.parse(init.body as string)).toEqual({ email: EMAIL, password: PASSWORD })
  })

  it('returns to the page the user came from after signing up', async () => {
    respond(201, ISSUED)
    const router = renderAt({ pathname: '/signup', state: { from: { pathname: '/jobs/7', search: '', hash: '' } } })

    await fill(EMAIL, PASSWORD, PASSWORD)

    await waitFor(() => expect(router.state.location.pathname).toBe('/jobs/7'))
  })

  it('says when the email already has an account and offers to sign in', async () => {
    respond(409, { error: { code: 'conflict', message: 'an account with this email already exists' } })
    const router = renderAt()

    await fill(EMAIL, PASSWORD, PASSWORD)

    expect(await screen.findByText('An account with this email already exists.')).toBeInTheDocument()
    expect(useSession.getState().token).toBeNull()
    await userEvent.setup().click(screen.getByRole('link', { name: 'Sign in instead' }))
    expect(router.state.location.pathname).toBe('/signin')
  })

  it('puts a server validation error on the field it is about', async () => {
    respond(422, {
      error: { code: 'validation_error', message: 'the request is invalid', details: [{ loc: ['body', 'email'], msg: 'bad', type: 'value_error' }] },
    })
    renderAt()

    await fill(EMAIL, PASSWORD, PASSWORD)

    expect(await screen.findByText('Enter a valid email address, like name@example.com.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create account/i })).toBeEnabled()
  })
})
