import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { shouldRequireSignIn } from '@/lib/auth'
import { useSession } from '@/stores/session'
import { RequireAuth } from './RequireAuth'

function renderGuarded(enforce: boolean) {
  const router = createMemoryRouter(
    [
      { path: '/signin', element: <p>Sign-in page</p> },
      {
        path: '/',
        element: (
          <RequireAuth enforce={enforce}>
            <p>Private app</p>
          </RequireAuth>
        ),
      },
    ],
    { initialEntries: ['/'] },
  )
  render(<RouterProvider router={router} />)
  return router
}

beforeEach(() => {
  window.sessionStorage.clear()
  useSession.setState({ activeProfileId: null, token: null })
})

describe('shouldRequireSignIn', () => {
  it('requires sign-in only for a signed-out user in a production build', () => {
    expect(shouldRequireSignIn(null, false)).toBe(true)
    expect(shouldRequireSignIn('key', false)).toBe(false)
  })

  it('never forces sign-in in development', () => {
    expect(shouldRequireSignIn(null, true)).toBe(false)
    expect(shouldRequireSignIn('key', true)).toBe(false)
  })
})

describe('RequireAuth', () => {
  it('redirects a signed-out user to the sign-in page and remembers where they were going', () => {
    const router = renderGuarded(true)

    expect(screen.getByText('Sign-in page')).toBeInTheDocument()
    expect(screen.queryByText('Private app')).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/signin')
    expect(router.state.location.state).toMatchObject({ from: { pathname: '/' } })
  })

  it('renders the app for a signed-in user', () => {
    useSession.setState({ token: 'key' })
    renderGuarded(true)

    expect(screen.getByText('Private app')).toBeInTheDocument()
  })

  it('lets a signed-out user through when sign-in is not enforced', () => {
    renderGuarded(false)

    expect(screen.getByText('Private app')).toBeInTheDocument()
  })
})
