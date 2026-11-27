import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import type { MatchingDraft, Me, Profile } from '@/api/types'
import { useSession } from '@/stores/session'
import { emptyCareer, named, NOT_FOUND, only, reply, type Call, type Reply } from '@/test/careerApi'
import { CONTENT_ERROR } from './formErrors'
import MatchingProfilesPage from './MatchingProfilesPage'
import { DRAFT_STATE_KEY } from './matchingDraft'

// jsdom has no ResizeObserver, which the Active switch (Radix) measures with.
globalThis.ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

// jsdom has no scrollIntoView, which moving to the first invalid field calls.
const scrollIntoView = vi.fn()
Element.prototype.scrollIntoView = scrollIntoView

const ME: Me = { email: 'ada@example.com', full_name: 'Ada Example', headline: 'Backend engineer' }

const PROFILE: Profile = {
  id: 1,
  name: 'Python backend',
  active: true,
  desired_titles: ['Backend Engineer'],
  required_skills: ['Python'],
  preferred_skills: [],
  seniorities: [],
  work_modes: [],
  employment_types: [],
  countries: [],
  locations: [],
  summary: 'Backend roles in fintech',
  min_score_override: null,
  embedding_status: 'ready',
  embedding_note: null,
  created_at: '2026-11-20T10:00:00Z',
  updated_at: '2026-11-21T10:00:00Z',
}

/** Answers the API by "METHOD /path"; anything not listed is a 404. Returns every call made, in order. */
function stubApi(routes: Record<string, Reply | (() => Promise<Reply>)>): Call[] {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      const path = String(input).replace(/^\/api/, '')
      calls.push({ method, path, init })
      const route = routes[`${method} ${path}`]
      const { status, body, headers } = typeof route === 'function' ? await route() : (route ?? NOT_FOUND)
      return new Response(body === undefined ? null : JSON.stringify(body), { status, headers })
    }),
  )
  return calls
}

function renderPage(state?: unknown): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[{ pathname: '/profile/matching', state }]}>
        <MatchingProfilesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const accountRoutes = () => ({ 'GET /me': reply(200, ME), 'GET /profiles': reply(200, { items: [PROFILE] }) })

beforeEach(() => {
  scrollIntoView.mockClear()
  window.localStorage.clear()
  window.sessionStorage.clear()
  useSession.setState({ activeProfileId: null, token: 'header.payload.signature' })
})

afterEach(() => vi.unstubAllGlobals())

describe('matching status note', () => {
  async function showStatus(profile: Partial<Profile>): Promise<void> {
    stubApi({ 'GET /me': reply(200, ME), 'GET /profiles': reply(200, { items: [{ ...PROFILE, ...profile }] }) })
    renderPage()
    await screen.findByRole('heading', { name: 'Basics' })
  }

  it('says matching is delayed and nothing is lost when the quota is used up', async () => {
    await showStatus({ embedding_status: 'pending', embedding_note: 'quota' })

    expect(screen.getByText('Matching is delayed: will retry')).toBeInTheDocument()
    expect(screen.getByText('The language-model quota is used up for now. Sanket retries automatically; nothing is lost.')).toBeInTheDocument()
  })

  it('keeps the usual pill and adds a retry line after another failure', async () => {
    await showStatus({ embedding_status: 'pending', embedding_note: 'error' })

    expect(screen.getByText('Preparing for matching')).toBeInTheDocument()
    expect(screen.getByText('A step failed; retrying automatically.')).toBeInTheDocument()
  })

  it('shows no extra line for a plain pending profile', async () => {
    await showStatus({ embedding_status: 'pending', embedding_note: null })

    expect(screen.getByText('Preparing for matching')).toBeInTheDocument()
    expect(screen.queryByText(/retrying automatically|quota/)).not.toBeInTheDocument()
  })

  it('keeps the current text for a failed profile', async () => {
    await showStatus({ embedding_status: 'failed', embedding_note: 'error' })

    expect(screen.getByText('Preparation failed: retrying')).toBeInTheDocument()
  })
})

const NOT_AN_ACCOUNT = reply(404, { error: { code: 'not_found', message: 'not an account' } })
const emptyRoutes = (me: Me | null = ME) => ({ 'GET /me': me ? reply(200, me) : NOT_AN_ACCOUNT, 'GET /profiles': reply(200, { items: [] }) })
const savedRoute = (name: string) => ({ 'POST /profiles': reply(201, { ...PROFILE, id: 2, name }) })
const createdName = (calls: Call[]) => (JSON.parse(only(calls, 'POST', '/profiles').init.body as string) as { name: string }).name

describe('Cancel and New profile', () => {
  it('offers New profile, and no Cancel, while a saved profile is open', async () => {
    stubApi(accountRoutes())
    renderPage()

    expect(await screen.findByRole('button', { name: /new profile/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /save changes/i })).toBeInTheDocument()
  })

  it('swaps New profile for a visible, enabled Cancel in the create state', async () => {
    stubApi(accountRoutes())
    renderPage()

    await userEvent.setup().click(await screen.findByRole('button', { name: /new profile/i }))

    const cancel = screen.getByRole('button', { name: 'Cancel' })
    expect(cancel).toBeEnabled()
    // The secondary style, not the faint ghost one.
    expect(cancel.className).toContain('bg-elevated')
    expect(cancel.className).not.toContain('text-muted')
    expect(screen.queryByRole('button', { name: /new profile/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create profile/i })).toBeInTheDocument()
    expect(screen.getByLabelText('Profile name')).toHaveValue('')
  })

  it('discards what was typed and every error, and returns to the saved profile', async () => {
    stubApi(accountRoutes())
    renderPage()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /new profile/i }))
    await user.type(screen.getByLabelText('Profile name'), 'Draft name')
    await user.click(screen.getByRole('button', { name: /create profile/i }))
    expect(await screen.findByText(CONTENT_ERROR)).toBeInTheDocument()
    await user.type(screen.getByLabelText('What you are looking for'), 'Something else')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText(CONTENT_ERROR)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /save changes/i })).toBeInTheDocument()
    expect(screen.getByLabelText('Profile name')).toHaveValue('Python backend')
    expect(screen.getByLabelText('What you are looking for')).toHaveValue('Backend roles in fintech')
    expect(screen.getByRole('button', { name: /new profile/i })).toBeInTheDocument()
  })

  it('opens straight in the create state, with neither New profile nor Cancel, when nothing is saved', async () => {
    stubApi(emptyRoutes())
    renderPage()

    expect(await screen.findByRole('button', { name: /create profile/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /new profile/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /save changes/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Delete this profile' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Profile name')).toHaveValue('')
  })

})

describe('the profile name', () => {
  it('keeps Profile name editable under Basics', async () => {
    stubApi(accountRoutes())
    renderPage()

    const profileName = await screen.findByLabelText('Profile name')
    expect(profileName).toBeEnabled()
    expect(profileName).toHaveValue('Python backend')
  })

  it('does not block a new user who left it empty, and names the profile from the headline', async () => {
    const calls = stubApi({ ...emptyRoutes({ ...ME, headline: 'Staff engineer' }), ...savedRoute('Staff engineer') })
    renderPage()
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('What you are looking for'), 'Backend roles')
    await user.click(screen.getByRole('button', { name: /create profile/i }))

    await waitFor(() => expect(named(calls, 'POST', '/profiles')).toHaveLength(1))
    expect(createdName(calls)).toBe('Staff engineer')
    expect(screen.queryByText(/Give the profile a name/)).not.toBeInTheDocument()
  })

  it('falls back to "My profile" when the headline is empty', async () => {
    const calls = stubApi({ ...emptyRoutes({ ...ME, headline: '' }), ...savedRoute('My profile') })
    renderPage()

    await userEvent.setup().type(await screen.findByLabelText('What you are looking for'), 'Backend roles')
    await userEvent.setup().click(screen.getByRole('button', { name: /create profile/i }))

    await waitFor(() => expect(named(calls, 'POST', '/profiles')).toHaveLength(1))
    expect(createdName(calls)).toBe('My profile')
  })

  it('falls back to "My profile" for a credential that has no account, so there is no headline', async () => {
    const calls = stubApi({ ...emptyRoutes(null), ...savedRoute('My profile') })
    renderPage()

    await userEvent.setup().type(await screen.findByLabelText('What you are looking for'), 'Backend roles')
    await userEvent.setup().click(screen.getByRole('button', { name: /create profile/i }))

    await waitFor(() => expect(named(calls, 'POST', '/profiles')).toHaveLength(1))
    expect(createdName(calls)).toBe('My profile')
  })

  it('shows the name it would use as the placeholder and in the hint', async () => {
    stubApi(emptyRoutes())
    renderPage()

    const name = await screen.findByLabelText('Profile name')
    expect(name).toHaveAttribute('placeholder', 'Backend engineer')
    expect(screen.getByText(/Left empty, the profile is called “Backend engineer”/)).toBeInTheDocument()
  })

  it('keeps a name the user typed', async () => {
    const calls = stubApi({ ...emptyRoutes(), ...savedRoute('Python backend') })
    renderPage()
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Profile name'), '  Python backend ')
    await user.type(screen.getByLabelText('What you are looking for'), 'Backend roles')
    await user.click(screen.getByRole('button', { name: /create profile/i }))

    await waitFor(() => expect(named(calls, 'POST', '/profiles')).toHaveLength(1))
    expect(createdName(calls)).toBe('Python backend')
  })

  it('numbers the default when another profile already has it, so a second one is not a conflict', async () => {
    const calls = stubApi({
      'GET /me': reply(200, { ...ME, headline: '' }),
      'GET /profiles': reply(200, { items: [{ ...PROFILE, name: 'My profile' }] }),
      ...savedRoute('My profile 2'),
    })
    renderPage()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /new profile/i }))
    await user.type(screen.getByLabelText('What you are looking for'), 'Backend roles')
    await user.click(screen.getByRole('button', { name: /create profile/i }))

    await waitFor(() => expect(named(calls, 'POST', '/profiles')).toHaveLength(1))
    expect(createdName(calls)).toBe('My profile 2')
  })
})

describe('validation errors', () => {
  it('shows the problem next to its field, focuses and scrolls to it, and summarises at the top', async () => {
    const calls = stubApi(emptyRoutes())
    renderPage()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /create profile/i }))

    const message = screen.getByText(CONTENT_ERROR)
    expect(message.closest('[data-field="profile.desired_titles"]')).not.toBeNull()
    expect(screen.getByText('Please fix this field: Preferred roles.')).toBeInTheDocument()
    expect(screen.getByLabelText('Preferred roles')).toHaveFocus()
    expect(scrollIntoView).toHaveBeenCalled()
    expect(named(calls, 'POST', '/profiles')).toHaveLength(0)
  })

  it('clears the error and the summary once the field is fixed', async () => {
    stubApi(emptyRoutes())
    renderPage()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /create profile/i }))
    await user.type(screen.getByLabelText('What you are looking for'), 'Backend roles')

    expect(screen.queryByText(CONTENT_ERROR)).not.toBeInTheDocument()
    expect(screen.queryByText(/Please fix/)).not.toBeInTheDocument()
  })

  it('shows a name conflict on the profile name field', async () => {
    stubApi({
      ...accountRoutes(),
      'PUT /profiles/1': reply(409, { error: { code: 'conflict', message: 'another profile has this name' } }),
    })
    renderPage()

    await userEvent.setup().click(await screen.findByRole('button', { name: /save changes/i }))

    const message = await screen.findByText('another profile has this name')
    expect(message.closest('[data-field="profile.name"]')).not.toBeNull()
    expect(screen.getByLabelText('Profile name')).toHaveFocus()
  })
})

describe('the career profile has its own pages', () => {
  it('shows no personal info and no CV import here', async () => {
    stubApi(accountRoutes())
    renderPage()

    await screen.findByRole('heading', { name: 'Basics' })
    expect(screen.queryByRole('heading', { name: 'Personal info' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Full name')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Import from CV' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('cv-file-input')).not.toBeInTheDocument()
    expect(screen.queryByText(/Your CV text is sent/)).not.toBeInTheDocument()
  })

  it('still works when the credential has no career profile', async () => {
    const calls = stubApi({ ...emptyRoutes(null), ...savedRoute('My profile') })
    renderPage()

    await userEvent.setup().type(await screen.findByLabelText('What you are looking for'), 'Backend roles')
    await userEvent.setup().click(screen.getByRole('button', { name: /create profile/i }))

    await waitFor(() => expect(named(calls, 'POST', '/profiles')).toHaveLength(1))
    expect(screen.queryByText(/You have a career profile/)).not.toBeInTheDocument()
  })
})

const DRAFT: MatchingDraft = {
  desired_titles: ['Staff Engineer', 'Platform Engineer'],
  required_skills: ['Go', 'Kubernetes'],
  preferred_skills: [],
  seniorities: ['senior'],
  locations: ['Berlin'],
  years_of_experience: 6.5,
}

const BANNER = /Pre-filled from your career profile \(about 6\.5 years of experience\)\. Review it, then press Create profile\. Nothing is created yet\./

const CAREER_WITH_SKILLS = reply(200, { ...emptyCareer(), skills: [{ id: 1, name: 'Go', level: null }] })

describe('a matching profile started from the career profile', () => {
  it('opens in the create state with the draft in the form, and creates nothing', async () => {
    const calls = stubApi(emptyRoutes())
    renderPage({ [DRAFT_STATE_KEY]: DRAFT })

    expect(await screen.findByText(BANNER)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create profile/i })).toBeInTheDocument()
    for (const tag of ['Staff Engineer', 'Platform Engineer', 'Go', 'Kubernetes', 'Berlin']) expect(screen.getByText(tag)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Senior' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getAllByText('From career profile')).toHaveLength(4)
    expect(calls.filter((call) => call.method !== 'GET')).toEqual([])
  })

  it('leaves out the experience figure when there is none', async () => {
    stubApi(emptyRoutes())
    renderPage({ [DRAFT_STATE_KEY]: { ...DRAFT, years_of_experience: null } })

    expect(await screen.findByText(/Pre-filled from your career profile\. Review it, then press Create profile\. Nothing is created yet\./)).toBeInTheDocument()
  })

  it('creates the profile only when Create profile is pressed, with the draft and a name from the headline', async () => {
    const calls = stubApi({ ...emptyRoutes(), ...savedRoute('Backend engineer') })
    renderPage({ [DRAFT_STATE_KEY]: DRAFT })

    await userEvent.setup().click(await screen.findByRole('button', { name: /create profile/i }))

    await waitFor(() => expect(named(calls, 'POST', '/profiles')).toHaveLength(1))
    expect(JSON.parse(only(calls, 'POST', '/profiles').init.body as string)).toMatchObject({
      name: 'Backend engineer',
      desired_titles: ['Staff Engineer', 'Platform Engineer'],
      required_skills: ['Go', 'Kubernetes'],
      seniorities: ['senior'],
      locations: ['Berlin'],
    })
  })

  it('opens in the create state even when profiles are saved, and Cancel returns to the saved one without the draft', async () => {
    const calls = stubApi(accountRoutes())
    renderPage({ [DRAFT_STATE_KEY]: DRAFT })
    const user = userEvent.setup()

    expect(await screen.findByText(BANNER)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create profile/i })).toBeInTheDocument()
    expect(screen.getByLabelText('Profile name')).toHaveValue('')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByText(BANNER)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /save changes/i })).toBeInTheDocument()
    expect(screen.getByLabelText('Profile name')).toHaveValue('Python backend')
    expect(screen.queryByText('Staff Engineer')).not.toBeInTheDocument()
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument()
    expect(screen.queryAllByText('From career profile')).toHaveLength(0)
    expect(calls.filter((call) => call.method !== 'GET')).toEqual([])
  })

  it('ignores router state that is not a draft', async () => {
    stubApi(accountRoutes())
    renderPage({ [DRAFT_STATE_KEY]: { desired_titles: 'nope' } })

    expect(await screen.findByRole('button', { name: /save changes/i })).toBeInTheDocument()
    expect(screen.queryByText(/Pre-filled/)).not.toBeInTheDocument()
  })

  it('offers to start from the career profile when nothing is saved and the career profile has content', async () => {
    stubApi({ ...emptyRoutes(), 'GET /career': CAREER_WITH_SKILLS })
    renderPage()

    expect(await screen.findByText(/You have a career profile\. Start from it/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create matching profile from my career profile' })).toBeEnabled()
  })

  it.each([
    ['a profile is saved', () => ({ ...accountRoutes(), 'GET /career': CAREER_WITH_SKILLS })],
    ['the career profile is empty', () => ({ ...emptyRoutes(), 'GET /career': reply(200, emptyCareer()) })],
    ['there is no career profile', () => emptyRoutes()],
  ])('does not offer it when %s', async (_name, routes) => {
    stubApi(routes())
    renderPage()

    await screen.findByRole('heading', { name: 'Basics' })
    expect(screen.queryByText(/You have a career profile/)).not.toBeInTheDocument()
  })
})
