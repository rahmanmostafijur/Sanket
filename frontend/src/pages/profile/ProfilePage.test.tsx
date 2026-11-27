import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import type { CvProposal, Me, Profile } from '@/api/types'
import { useSession } from '@/stores/session'
import ProfilePage from './ProfilePage'

// jsdom has no ResizeObserver, which the Active switch (Radix) measures with.
globalThis.ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const ME: Me = { email: 'ada@example.com', full_name: 'Ada Example', headline: 'Backend engineer', location: 'Berlin', summary: 'Builds APIs.' }

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

const EMPTY_PROPOSAL: CvProposal = {
  personal: { full_name: '', headline: '', location: '', summary: '' },
  profile: {
    desired_titles: [],
    required_skills: [],
    preferred_skills: [],
    seniorities: [],
    work_modes: [],
    employment_types: [],
    countries: [],
    locations: [],
    summary: '',
  },
}

const FULL_PROPOSAL: CvProposal = {
  personal: { full_name: 'Grace Sample', headline: 'Platform engineer', location: 'Dhaka', summary: 'Keeps systems up.' },
  profile: {
    desired_titles: ['Platform Engineer'],
    required_skills: ['Go', 'Kubernetes'],
    preferred_skills: ['Terraform'],
    seniorities: ['senior'],
    work_modes: ['remote'],
    employment_types: ['full_time'],
    countries: ['BD'],
    locations: ['Dhaka'],
    summary: 'Platform roles at product companies',
  },
}

interface Call {
  method: string
  path: string
  init: RequestInit
}

type Reply = { status: number; body?: unknown; headers?: Record<string, string> }

function reply(status: number, body?: unknown, headers: Record<string, string> = {}): Reply {
  return { status, body, headers }
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
      const { status, body, headers } = typeof route === 'function' ? await route() : (route ?? reply(404, { error: { code: 'not_found', message: 'not found' } }))
      return new Response(body === undefined ? null : JSON.stringify(body), { status, headers })
    }),
  )
  return calls
}

function renderPage(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const accountRoutes = () => ({ 'GET /me': reply(200, ME), 'GET /profiles': reply(200, { items: [PROFILE] }) })

const named = (calls: Call[], method: string, path: string) => calls.filter((call) => call.method === method && call.path === path)

function only(calls: Call[], method: string, path: string): Call {
  const [call, ...rest] = named(calls, method, path)
  if (!call || rest.length) throw new Error(`expected exactly one ${method} ${path}`)
  return call
}

/** A PDF or DOCX to drop on the form. `type` is left empty like a browser does for an unknown type. */
function cvFile(name = 'cv.pdf'): File {
  return new File(['fake cv bytes'], name, { type: 'application/pdf' })
}

async function pickFile(file: File): Promise<void> {
  const [input] = await screen.findAllByTestId('cv-file-input')
  if (!input) throw new Error('no file input')
  // Off by default in the app's own check, so a wrong extension reaches our code like it would from drag and drop.
  await userEvent.setup({ applyAccept: false }).upload(input, file)
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  useSession.setState({ activeProfileId: null, token: 'header.payload.signature' })
})

afterEach(() => vi.unstubAllGlobals())

describe('personal info section', () => {
  it('is the first section and holds the account details for an account', async () => {
    stubApi(accountRoutes())
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Personal info' })).toBeInTheDocument()
    const headings = screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent)
    expect(headings.indexOf('Personal info')).toBeLessThan(headings.indexOf('Basics'))
    expect(screen.getByLabelText('Full name')).toHaveValue('Ada Example')
    expect(screen.getByLabelText('Headline')).toHaveValue('Backend engineer')
    expect(screen.getByLabelText('Location')).toHaveValue('Berlin')
    expect(screen.getByLabelText('Short summary')).toHaveValue('Builds APIs.')
    expect(screen.getByLabelText('Full name')).toHaveAttribute('maxlength', '100')
    expect(screen.getByLabelText('Headline')).toHaveAttribute('maxlength', '120')
    expect(screen.getByLabelText('Location')).toHaveAttribute('maxlength', '100')
    expect(screen.getByLabelText('Short summary')).toHaveAttribute('maxlength', '600')
    expect(screen.getByText('12 / 600 characters. A few lines about who you are.')).toBeInTheDocument()
  })

  it('is hidden when /me answers 404, as for an API key', async () => {
    stubApi({ 'GET /me': reply(404, { error: { code: 'not_found', message: 'not an account' } }), 'GET /profiles': reply(200, { items: [PROFILE] }) })
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Basics' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Personal info' })).not.toBeInTheDocument()
  })

  it('renames the profile summary to what the user is looking for', async () => {
    stubApi(accountRoutes())
    renderPage()

    expect(await screen.findByRole('heading', { name: 'What you are looking for' })).toBeInTheDocument()
    expect(screen.getByLabelText('What you are looking for')).toHaveValue('Backend roles in fintech')
    expect(screen.queryByRole('heading', { name: 'About you' })).not.toBeInTheDocument()
  })

  it('saves the account first, then the profile', async () => {
    const saved = { ...ME, headline: 'Staff engineer' }
    const calls = stubApi({ ...accountRoutes(), 'PUT /me': reply(200, saved), 'PUT /profiles/1': reply(200, PROFILE) })
    renderPage()
    const user = userEvent.setup()

    const headline = await screen.findByLabelText('Headline')
    await user.clear(headline)
    await user.type(headline, ' Staff engineer ')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(named(calls, 'PUT', '/profiles/1')).toHaveLength(1))
    const writes = calls.filter((call) => call.method === 'PUT').map((call) => call.path)
    expect(writes).toEqual(['/me', '/profiles/1'])
    expect(JSON.parse(only(calls, 'PUT', '/me').init.body as string)).toEqual({
      full_name: 'Ada Example',
      headline: 'Staff engineer',
      location: 'Berlin',
      summary: 'Builds APIs.',
    })
  })

  it('does not call PUT /me when the personal info did not change', async () => {
    const calls = stubApi({ ...accountRoutes(), 'PUT /profiles/1': reply(200, PROFILE) })
    renderPage()

    await userEvent.setup().click(await screen.findByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(named(calls, 'PUT', '/profiles/1')).toHaveLength(1))
    expect(named(calls, 'PUT', '/me')).toHaveLength(0)
  })

  it('shows what the server rejected and does not save the profile', async () => {
    const calls = stubApi({
      ...accountRoutes(),
      'PUT /me': reply(422, { error: { code: 'validation_error', message: 'invalid request', details: [{ loc: ['body', 'full_name'], msg: 'must not contain links' }] } }),
    })
    renderPage()
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText('Full name'), ' Jr')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    expect(await screen.findByText('must not contain links')).toBeInTheDocument()
    expect(named(calls, 'PUT', '/profiles/1')).toHaveLength(0)
  })
})

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

describe('CV import', () => {
  it('always shows what happens to the CV text', async () => {
    stubApi(accountRoutes())
    renderPage()

    expect(await screen.findByText('Your CV text is sent to the language-model provider to read it. The file and its text are not stored.')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Import from CV' }).length).toBeGreaterThanOrEqual(1)
  })

  it('rejects a wrong extension before sending anything', async () => {
    const calls = stubApi(accountRoutes())
    renderPage()

    await pickFile(new File(['hello'], 'cv.txt', { type: 'text/plain' }))

    expect(await screen.findByText('Only PDF and DOCX files are supported.')).toBeInTheDocument()
    expect(named(calls, 'POST', '/cv/import')).toHaveLength(0)
  })

  it('rejects a file over 5 MB before sending anything', async () => {
    const calls = stubApi(accountRoutes())
    renderPage()

    await pickFile(Object.defineProperty(cvFile(), 'size', { value: 5 * 1024 * 1024 + 1 }))

    expect(await screen.findByText('That file is larger than 5 MB.')).toBeInTheDocument()
    expect(named(calls, 'POST', '/cv/import')).toHaveLength(0)
  })

  it('sends the raw file and fills the form from the answer without saving anything', async () => {
    const calls = stubApi({ ...accountRoutes(), 'POST /cv/import': reply(200, FULL_PROPOSAL) })
    renderPage()
    const file = cvFile()

    await pickFile(file)

    expect(await screen.findByText(/Imported from your CV: 13 fields filled\. Review them, then press Save\. Nothing is saved yet\./)).toBeInTheDocument()
    const upload = only(calls, 'POST', '/cv/import')
    expect(upload.init.body).toBe(file)
    expect((upload.init.headers as Record<string, string>)['Content-Type']).toBe('application/pdf')
    expect(screen.getByLabelText('Full name')).toHaveValue('Grace Sample')
    expect(screen.getByLabelText('Headline')).toHaveValue('Platform engineer')
    expect(screen.getByLabelText('Location')).toHaveValue('Dhaka')
    expect(screen.getByLabelText('Short summary')).toHaveValue('Keeps systems up.')
    expect(screen.getByLabelText('What you are looking for')).toHaveValue('Platform roles at product companies')
    expect(screen.getByText('Platform Engineer')).toBeInTheDocument()
    expect(screen.getByText('Kubernetes')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Senior' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Remote' })).toHaveAttribute('aria-pressed', 'true')
    // The profile's own name is not the CV's to change.
    expect(screen.getByLabelText('Profile name')).toHaveValue('Python backend')
    expect(screen.getAllByText('Filled from CV')).toHaveLength(13)
    expect(calls.filter((call) => call.method !== 'GET' && call.path !== '/cv/import')).toEqual([])
  })

  it('keeps the current value of every field the CV did not state', async () => {
    stubApi({
      ...accountRoutes(),
      'POST /cv/import': reply(200, { ...EMPTY_PROPOSAL, personal: { ...EMPTY_PROPOSAL.personal, full_name: 'Grace Sample' }, profile: { ...EMPTY_PROPOSAL.profile, preferred_skills: ['Terraform'] } }),
    })
    renderPage()

    await pickFile(cvFile())

    expect(await screen.findByText(/Imported from your CV: 2 fields filled/)).toBeInTheDocument()
    expect(screen.getByLabelText('Full name')).toHaveValue('Grace Sample')
    expect(screen.getByLabelText('Headline')).toHaveValue('Backend engineer')
    expect(screen.getByLabelText('What you are looking for')).toHaveValue('Backend roles in fintech')
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument()
    expect(screen.getByText('Python')).toBeInTheDocument()
    expect(screen.getByText('Terraform')).toBeInTheDocument()
  })

  it('drops the mark from a field once the user edits it, and the banner on Dismiss', async () => {
    stubApi({ ...accountRoutes(), 'POST /cv/import': reply(200, FULL_PROPOSAL) })
    renderPage()
    const user = userEvent.setup()

    await pickFile(cvFile())
    await screen.findByText(/Imported from your CV/)
    await user.type(screen.getByLabelText('Headline'), '!')
    expect(screen.getAllByText('Filled from CV')).toHaveLength(12)
    await user.click(screen.getByRole('button', { name: /dismiss/i }))

    expect(screen.queryByText(/Imported from your CV/)).not.toBeInTheDocument()
    expect(screen.getAllByText('Filled from CV')).toHaveLength(12)
  })

  it('shows a progress state and blocks saving while the CV is read', async () => {
    let finish: (value: Reply) => void = () => undefined
    stubApi({ ...accountRoutes(), 'POST /cv/import': () => new Promise<Reply>((resolve) => (finish = resolve)) })
    renderPage()

    await pickFile(cvFile())

    expect(await screen.findByText('Reading your CV...')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled()
    for (const button of screen.getAllByRole('button', { name: 'Import from CV' })) expect(button).toBeDisabled()
    finish(reply(200, EMPTY_PROPOSAL))
    await waitFor(() => expect(screen.queryByText('Reading your CV...')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled()
  })

  it.each([
    ['413', reply(413, { error: { code: 'too_large', message: 'file too large' } }), 'That file is larger than 5 MB.'],
    [
      '422',
      reply(422, { error: { code: 'unreadable', message: 'This PDF has no text. Use a text-based PDF or DOCX.' } }),
      'This PDF has no text. Use a text-based PDF or DOCX.',
    ],
    ['429', reply(429, { error: { code: 'rate_limited', message: 'slow down' } }, { 'Retry-After': '30' }), 'Too many imports. Try again in 30 seconds.'],
    [
      '503',
      reply(503, { error: { code: 'quota', message: 'quota exhausted' } }, { 'Retry-After': '600' }),
      'The language model is unavailable right now (quota). Try again in 10 minutes.',
    ],
    ['502', reply(502, { error: { code: 'provider', message: 'upstream said no' } }), 'Could not read the CV. Try again.'],
  ])('explains a %s answer', async (_status, response, message) => {
    stubApi({ ...accountRoutes(), 'POST /cv/import': response })
    renderPage()

    await pickFile(cvFile())

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(message)).toBeInTheDocument()
    expect(screen.getByLabelText('Full name')).toHaveValue('Ada Example')
  })
})
