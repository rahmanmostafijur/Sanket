import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NAV_ITEMS } from '@/components/layout/nav'
import { useSession } from '@/stores/session'
import { accountToken, reply, stubBackend, stubBrowserGaps } from '@/test/careerApi'
import { preloadProfileArea, renderProfileArea } from '@/test/renderProfileArea'

stubBrowserGaps()

beforeAll(preloadProfileArea, 30_000)

beforeEach(() => {
  window.localStorage.clear()
  useSession.setState({ activeProfileId: null, token: accountToken() })
})

afterEach(() => vi.unstubAllGlobals())

describe('navigation', () => {
  it('calls the sidebar entry Profile and keeps it at /profile', () => {
    expect(NAV_ITEMS.find((item) => item.to === '/profile')?.label).toBe('Profile')
    expect(NAV_ITEMS.some((item) => item.label === 'Matching profile')).toBe(false)
  })

  it('has a link to each section, and marks the current one', async () => {
    stubBackend()
    renderProfileArea('/profile/education')

    const tabs = within(await screen.findByRole('navigation', { name: 'Profile sections' }))
    const links = tabs.getAllByRole('link').map((link) => [link.textContent, link.getAttribute('href')])
    expect(links).toEqual([
      ['Overview', '/profile'],
      ['Personal', '/profile/personal'],
      ['Education', '/profile/education'],
      ['Experience', '/profile/experience'],
      ['Skills and languages', '/profile/skills'],
      ['Accomplishments', '/profile/accomplishments'],
      ['Matching profiles', '/profile/matching'],
    ])
    expect(tabs.getByRole('link', { name: 'Education' })).toHaveAttribute('aria-current', 'page')
    expect(tabs.getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current')
  })

  it('moves between sections without leaving the layout', async () => {
    stubBackend({ routes: { 'GET /profiles': reply(200, { items: [] }) } })
    renderProfileArea('/profile')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('link', { name: 'Experience' }))
    expect(await screen.findByText('No experience yet')).toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: 'Accomplishments' }))
    expect(await screen.findByText('No certifications yet')).toBeInTheDocument()
    expect(screen.getByText('No projects yet')).toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: 'Matching profiles' }))
    expect(await screen.findByRole('heading', { name: 'Matching profiles' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Profile' })).toBeInTheDocument()
  })
})

describe('routes', () => {
  it.each([
    ['/profile', 'Profile completeness'],
    ['/profile/personal', 'Personal'],
    ['/profile/education', 'Education'],
    ['/profile/experience', 'Experience'],
    ['/profile/skills', 'Skills'],
    ['/profile/accomplishments', 'Certifications'],
  ])('%s shows its section', async (path, heading) => {
    stubBackend()
    renderProfileArea(path)

    expect(await screen.findByRole('heading', { level: 2, name: heading })).toBeInTheDocument()
  })

  it('/profile/matching shows the matching profile page, which works without a career profile', async () => {
    stubBackend({
      routes: {
        'GET /career': reply(404, { error: { code: 'not_found', message: 'this credential has no account' } }),
        'GET /profiles': reply(200, { items: [] }),
      },
    })
    renderProfileArea('/profile/matching')

    expect(await screen.findByRole('heading', { name: 'Basics' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create profile/i })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Personal info' })).not.toBeInTheDocument()
  })
})
