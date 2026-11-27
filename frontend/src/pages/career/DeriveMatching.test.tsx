import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { MatchingDraft, Profile } from '@/api/types'
import { useSession } from '@/stores/session'
import { accountToken, emptyCareer, named, only, reply, stubBackend, stubBrowserGaps, type Reply } from '@/test/careerApi'
import { preloadProfileArea, renderProfileArea } from '@/test/renderProfileArea'

stubBrowserGaps()

const CAREER = { ...emptyCareer(), skills: [{ id: 1, name: 'Go', level: null }], years_of_experience: 6.5 }

const DRAFT: MatchingDraft = {
  desired_titles: ['Backend Engineer'],
  required_skills: ['Go'],
  preferred_skills: ['Docker'],
  seniorities: ['senior'],
  locations: ['Berlin'],
  years_of_experience: 6.5,
}

const SAVED: Profile = {
  id: 1,
  name: 'Python backend',
  active: true,
  desired_titles: ['Data Engineer'],
  required_skills: ['Python'],
  preferred_skills: [],
  seniorities: [],
  work_modes: [],
  employment_types: [],
  countries: [],
  locations: [],
  summary: '',
  min_score_override: null,
  embedding_status: 'ready',
  embedding_note: null,
  created_at: '2026-11-20T10:00:00Z',
  updated_at: '2026-11-21T10:00:00Z',
}

const BUTTON = { name: 'Create matching profile from my career profile' }

beforeAll(preloadProfileArea, 30_000)

beforeEach(() => {
  window.localStorage.clear()
  useSession.setState({ activeProfileId: null, token: accountToken() })
})

afterEach(() => vi.unstubAllGlobals())

describe('Create matching profile from my career profile', () => {
  it('asks for a draft without a body, opens the matching page in the create state with it, and creates nothing', async () => {
    const backend = stubBackend({
      career: CAREER,
      routes: { 'POST /career/matching-draft': reply(200, DRAFT), 'GET /profiles': reply(200, { items: [] }) },
    })
    renderProfileArea('/profile')

    await userEvent.setup().click(await screen.findByRole('button', BUTTON))

    expect(await screen.findByText(/Pre-filled from your career profile \(about 6\.5 years of experience\)\. Review it, then press Create profile\. Nothing is created yet\./)).toBeInTheDocument()
    expect(only(backend.calls, 'POST', '/career/matching-draft').init.body).toBeUndefined()
    expect(screen.getByRole('button', { name: /create profile/i })).toBeInTheDocument()
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument()
    expect(screen.getByText('Docker')).toBeInTheDocument()
    expect(screen.getByText('Berlin')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Senior' })).toHaveAttribute('aria-pressed', 'true')
    expect(backend.calls.filter((call) => call.method !== 'GET' && call.path !== '/career/matching-draft')).toEqual([])
  })

  it('shows progress and disables the button while the draft is made', async () => {
    let finish: (value: Reply) => void = () => undefined
    stubBackend({
      career: CAREER,
      routes: { 'POST /career/matching-draft': () => new Promise<Reply>((resolve) => (finish = resolve)), 'GET /profiles': reply(200, { items: [] }) },
    })
    renderProfileArea('/profile')

    await userEvent.setup().click(await screen.findByRole('button', BUTTON))

    expect(await screen.findByText('Reading your career profile...')).toBeInTheDocument()
    expect(screen.getByRole('button', BUTTON)).toBeDisabled()
    finish(reply(200, DRAFT))
    expect(await screen.findByText(/Pre-filled from your career profile/)).toBeInTheDocument()
  })

  it('shows the server message on the Overview when there is nothing to build from, and stays there', async () => {
    stubBackend({
      career: CAREER,
      routes: { 'POST /career/matching-draft': reply(422, { error: { code: 'nothing_to_use', message: 'Add experience or skills to your career profile first.' } }) },
    })
    renderProfileArea('/profile')

    await userEvent.setup().click(await screen.findByRole('button', BUTTON))

    expect(await screen.findByText('Add experience or skills to your career profile first.')).toBeInTheDocument()
    expect(screen.getByRole('button', BUTTON)).toBeEnabled()
    expect(screen.getByRole('heading', { name: 'Profile completeness' })).toBeInTheDocument()
  })

  it('says what is missing even when the 422 has no error envelope', async () => {
    stubBackend({ career: CAREER, routes: { 'POST /career/matching-draft': reply(422, { message: 'add experience or skills first' }) } })
    renderProfileArea('/profile')

    await userEvent.setup().click(await screen.findByRole('button', BUTTON))

    expect(await screen.findByText('Add experience or skills to your career profile first.')).toBeInTheDocument()
  })

  it('opens in the create state when profiles are saved, and Cancel returns to the saved one and drops the draft', async () => {
    const backend = stubBackend({
      career: CAREER,
      routes: { 'POST /career/matching-draft': reply(200, DRAFT), 'GET /profiles': reply(200, { items: [SAVED] }) },
    })
    renderProfileArea('/profile')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', BUTTON))
    expect(await screen.findByText(/Pre-filled from your career profile/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create profile/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByText(/Pre-filled/)).not.toBeInTheDocument()
    expect(screen.getByLabelText('Profile name')).toHaveValue('Python backend')
    expect(screen.getByText('Data Engineer')).toBeInTheDocument()
    expect(screen.queryByText('Backend Engineer')).not.toBeInTheDocument()
    expect(named(backend.calls, 'POST', '/profiles')).toHaveLength(0)
  })

  it('creates the profile only when Create profile is pressed', async () => {
    const backend = stubBackend({
      career: CAREER,
      routes: {
        'POST /career/matching-draft': reply(200, DRAFT),
        'GET /profiles': reply(200, { items: [] }),
        'POST /profiles': reply(201, { ...SAVED, id: 2, name: 'My profile' }),
      },
    })
    renderProfileArea('/profile')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', BUTTON))
    await user.click(await screen.findByRole('button', { name: /create profile/i }))

    await waitFor(() => expect(named(backend.calls, 'POST', '/profiles')).toHaveLength(1))
    expect(JSON.parse(only(backend.calls, 'POST', '/profiles').init.body as string)).toMatchObject({ desired_titles: ['Backend Engineer'], required_skills: ['Go'], preferred_skills: ['Docker'] })
  })

  it('also starts from the matching page when nothing is saved there', async () => {
    stubBackend({
      career: CAREER,
      routes: { 'POST /career/matching-draft': reply(200, DRAFT), 'GET /profiles': reply(200, { items: [] }) },
    })
    renderProfileArea('/profile/matching')

    await userEvent.setup().click(await screen.findByRole('button', BUTTON))

    expect(await screen.findByText(/Pre-filled from your career profile/)).toBeInTheDocument()
    expect(screen.queryByText(/You have a career profile\. Start from it/)).not.toBeInTheDocument()
  })
})
