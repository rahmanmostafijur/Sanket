import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CvProposal } from '@/api/types'
import { useSession } from '@/stores/session'
import { accountToken, bodyOf, emptyCareer, named, only, reply, stubBackend, stubBrowserGaps, type Reply } from '@/test/careerApi'
import { preloadProfileArea, renderProfileArea } from '@/test/renderProfileArea'

stubBrowserGaps()

const NOTHING: CvProposal = {
  personal: { full_name: '', headline: '', summary: '', country: '', city: '', github_url: '', linkedin_url: '', portfolio_url: '' },
  education: [],
  experience: [],
  skills: [],
  languages: [],
  certifications: [],
  projects: [],
}

const PROPOSAL: CvProposal = {
  ...NOTHING,
  personal: { ...NOTHING.personal, full_name: 'Grace Sample', headline: 'Platform engineer', country: 'bd' },
  education: [
    { institution: 'Example University', degree: 'BSc', field: '', start: '2015-09', end: '2019-06', grade: '' },
    { institution: 'Sample College', degree: 'MSc', field: '', start: '2020-01', end: null, grade: '' },
  ],
  skills: [{ name: 'Go', level: null }, { name: 'python', level: null }],
}

const SAVED = {
  personal: { ...emptyCareer().personal, full_name: 'Ada Example', headline: 'Backend engineer', city: 'Berlin', availability: 'open_to_offers' as const },
  education: [{ id: 1, institution: 'Example University', degree: 'BSc', field: '', start: '2015-09', end: '2019-06', grade: '' }],
  skills: [{ id: 2, name: 'Python', level: null }],
  years_of_experience: 6.5,
}

beforeAll(preloadProfileArea, 30_000)

beforeEach(() => {
  window.localStorage.clear()
  useSession.setState({ activeProfileId: null, token: accountToken() })
})

afterEach(() => vi.unstubAllGlobals())

function cvFile(name = 'cv.pdf'): File {
  return new File(['fake cv bytes'], name, { type: 'application/pdf' })
}

async function pickFile(file: File): Promise<void> {
  const input = await screen.findByTestId('cv-file-input')
  // Off by default in the app's own check, so a wrong extension reaches our code like it would from drag and drop.
  await userEvent.setup({ applyAccept: false }).upload(input, file)
}

describe('completeness', () => {
  it('shows the percentage and links each empty section to its page', async () => {
    stubBackend({ career: SAVED })
    renderProfileArea('/profile')

    expect(await screen.findByText('43%')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Profile completeness' })).toHaveAttribute('aria-valuenow', '43')
    const empty = [
      ['Experience', '/profile/experience'],
      ['Languages', '/profile/skills'],
      ['Certifications', '/profile/accomplishments'],
      ['Projects', '/profile/accomplishments'],
    ]
    for (const [label, path] of empty) {
      expect(screen.getByRole('link', { name: new RegExp(`^${label} is empty`) })).toHaveAttribute('href', path)
    }
    // Sections with data are not offered as something to fill in.
    expect(screen.queryByRole('link', { name: /^Skills is empty/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^Personal is empty/ })).not.toBeInTheDocument()
  })

  it('shows 0% and every section as empty for a new account', async () => {
    stubBackend()
    renderProfileArea('/profile')

    expect(await screen.findByText('0%')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /is empty/ })).toHaveLength(7)
  })

  it('shows the availability here and says it is changed in Personal, and the years of experience', async () => {
    stubBackend({ career: SAVED })
    renderProfileArea('/profile')

    expect(await screen.findByText('Open to offers')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Change in Personal' })).toHaveAttribute('href', '/profile/personal')
    expect(screen.getByText('About 6.5 years')).toBeInTheDocument()
  })

  it('shows an error with a retry when the career profile cannot be read', async () => {
    stubBackend({ routes: { 'GET /career': reply(500, { error: { code: 'boom', message: 'The server broke' } }) } })
    renderProfileArea('/profile')

    expect(await screen.findByText('The server broke')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('the CV import entry point', () => {
  it('is one button, one file input and one privacy note', async () => {
    stubBackend()
    renderProfileArea('/profile')

    await screen.findByText('0%')
    expect(screen.getAllByRole('button', { name: 'Import from CV' })).toHaveLength(1)
    expect(screen.getAllByTestId('cv-file-input')).toHaveLength(1)
    expect(screen.getAllByText('Your CV text is sent to the language-model provider to read it. The file and its text are not stored.')).toHaveLength(1)
  })

  it('is on no other page of the profile area', async () => {
    stubBackend()
    renderProfileArea('/profile/personal')

    await screen.findByText('No personal details yet')
    expect(screen.queryByRole('button', { name: 'Import from CV' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('cv-file-input')).not.toBeInTheDocument()
  })

  it('rejects a wrong extension and a file over 5 MB before sending anything', async () => {
    const backend = stubBackend()
    renderProfileArea('/profile')

    await pickFile(new File(['hello'], 'cv.txt', { type: 'text/plain' }))
    expect(await screen.findByText('Only PDF and DOCX files are supported.')).toBeInTheDocument()
    await pickFile(Object.defineProperty(cvFile(), 'size', { value: 5 * 1024 * 1024 + 1 }))
    expect(await screen.findByText('That file is larger than 5 MB.')).toBeInTheDocument()
    expect(named(backend.calls, 'POST', '/cv/import')).toHaveLength(0)
  })

  it('shows progress and disables the button while the CV is read', async () => {
    let finish: (value: Reply) => void = () => undefined
    stubBackend({ routes: { 'POST /cv/import': () => new Promise<Reply>((resolve) => (finish = resolve)) } })
    renderProfileArea('/profile')

    await pickFile(cvFile())

    expect(await screen.findByText('Reading your CV...')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import from CV' })).toBeDisabled()
    finish(reply(200, NOTHING))
    expect(await screen.findByText('Nothing new was found in that CV.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import from CV' })).toBeEnabled()
  })

  it.each([
    ['413', reply(413, { error: { code: 'too_large', message: 'file too large' } }), 'That file is larger than 5 MB.'],
    ['422', reply(422, { error: { code: 'unreadable', message: 'This PDF has no text. Use a text-based PDF or DOCX.' } }), 'This PDF has no text. Use a text-based PDF or DOCX.'],
    ['429', reply(429, { error: { code: 'rate_limited', message: 'slow down' } }, { 'Retry-After': '30' }), 'Too many imports. Try again in 30 seconds.'],
    ['503', reply(503, { error: { code: 'quota', message: 'quota exhausted' } }, { 'Retry-After': '600' }), 'The language model is unavailable right now (quota). Try again in 10 minutes.'],
    ['502', reply(502, { error: { code: 'provider', message: 'upstream said no' } }), 'Could not read the CV. Try again.'],
  ])('explains a %s answer', async (_status, response, message) => {
    stubBackend({ routes: { 'POST /cv/import': response } })
    renderProfileArea('/profile')

    await pickFile(cvFile())

    expect(await screen.findByText(message)).toBeInTheDocument()
  })
})

describe('a CV proposal', () => {
  it('is sent as the raw file and saves nothing', async () => {
    const backend = stubBackend({ career: SAVED, routes: { 'POST /cv/import': reply(200, PROPOSAL) } })
    renderProfileArea('/profile')
    const file = cvFile()

    await pickFile(file)

    expect(await screen.findByText(/Your CV was read/)).toBeInTheDocument()
    const upload = only(backend.calls, 'POST', '/cv/import')
    expect(upload.init.body).toBe(file)
    expect((upload.init.headers as Record<string, string>)['Content-Type']).toBe('application/pdf')
    expect(backend.calls.filter((call) => call.method !== 'GET' && call.path !== '/cv/import')).toEqual([])
    // Links to the sections that have something to review: 3 personal fields, 1 new education row, 1 new skill.
    const result = within(screen.getByText(/Your CV was read/).closest('div') as HTMLElement)
    expect(result.getByRole('link', { name: 'Personal' })).toHaveAttribute('href', '/profile/personal')
    expect(result.getByText('(3)')).toBeInTheDocument()
    expect(result.getByRole('link', { name: 'Education' }).parentElement).toHaveTextContent('Education (1)')
    expect(result.getByRole('link', { name: 'Skills' }).parentElement).toHaveTextContent('Skills (1)')
    expect(result.queryByRole('link', { name: 'Projects' })).not.toBeInTheDocument()
  })

  it('opens Personal in its editor with the CV values merged in, marked, and a banner; saves only on Save', async () => {
    const backend = stubBackend({ career: SAVED, routes: { 'POST /cv/import': reply(200, PROPOSAL) } })
    renderProfileArea('/profile')
    const user = userEvent.setup()
    await pickFile(cvFile())
    await screen.findByText(/Your CV was read/)

    await user.click(within(screen.getByText(/Your CV was read/).closest('div') as HTMLElement).getByRole('link', { name: 'Personal' }))

    expect(await screen.findByText('Filled from your CV: 3 fields. Review them, then press Save. Nothing is saved yet.')).toBeInTheDocument()
    expect(screen.getByLabelText('Full name')).toHaveValue('Grace Sample')
    expect(screen.getByLabelText('Headline')).toHaveValue('Platform engineer')
    expect(screen.getByLabelText('Country')).toHaveValue('BD')
    // What the CV did not state is kept.
    expect(screen.getByLabelText('City')).toHaveValue('Berlin')
    expect(screen.getByLabelText('Availability')).toHaveValue('open_to_offers')
    expect(screen.getAllByText('Filled from CV')).toHaveLength(3)
    expect(named(backend.calls, 'PUT', '/career/personal')).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByRole('button', { name: 'Edit Personal' })).toBeInTheDocument()
    expect(bodyOf(only(backend.calls, 'PUT', '/career/personal'))).toMatchObject({ full_name: 'Grace Sample', headline: 'Platform engineer', country: 'BD', city: 'Berlin', availability: 'open_to_offers' })
    expect(screen.queryByText(/Filled from your CV/)).not.toBeInTheDocument()
  })

  it('drops a field mark once the user edits that field, and the banner on Dismiss', async () => {
    stubBackend({ career: SAVED, routes: { 'POST /cv/import': reply(200, PROPOSAL) } })
    renderProfileArea('/profile')
    const user = userEvent.setup()
    await pickFile(cvFile())
    await screen.findByText(/Your CV was read/)
    await user.click(within(screen.getByText(/Your CV was read/).closest('div') as HTMLElement).getByRole('link', { name: 'Personal' }))
    await screen.findByText(/Filled from your CV: 3 fields/)

    await user.type(screen.getByLabelText('Headline'), '!')
    expect(screen.getAllByText('Filled from CV')).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: /dismiss/i }))

    expect(screen.queryByText(/Filled from your CV/)).not.toBeInTheDocument()
    expect(screen.getAllByText('Filled from CV')).toHaveLength(2)
  })

  it('appends new education rows to the saved ones and skips a duplicate, then saves them all together', async () => {
    const backend = stubBackend({ career: SAVED, routes: { 'POST /cv/import': reply(200, PROPOSAL) } })
    renderProfileArea('/profile')
    const user = userEvent.setup()
    await pickFile(cvFile())
    await screen.findByText(/Your CV was read/)
    await user.click(within(screen.getByText(/Your CV was read/).closest('div') as HTMLElement).getByRole('link', { name: 'Education' }))

    expect(await screen.findByText('Filled from your CV: 1 row. Review them, then press Save. Nothing is saved yet.')).toBeInTheDocument()
    const rows = Array.from(document.querySelectorAll<HTMLElement>('[data-row]'))
    expect(rows).toHaveLength(2)
    expect(within(rows[0] as HTMLElement).getByLabelText('Institution')).toHaveValue('Example University')
    expect(within(rows[1] as HTMLElement).getByLabelText('Institution')).toHaveValue('Sample College')
    expect(within(rows[1] as HTMLElement).getByText('Filled from CV')).toBeInTheDocument()
    expect(within(rows[0] as HTMLElement).queryByText('Filled from CV')).not.toBeInTheDocument()
    expect(named(backend.calls, 'PUT', '/career/education')).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByText('Sample College')).toBeInTheDocument()
    expect((bodyOf(only(backend.calls, 'PUT', '/career/education')) as { items: { institution: string }[] }).items.map((item) => item.institution)).toEqual(['Example University', 'Sample College'])
  })

  it('discards the merge for a section on Cancel, and that section is not offered again', async () => {
    const backend = stubBackend({ career: SAVED, routes: { 'POST /cv/import': reply(200, PROPOSAL) } })
    renderProfileArea('/profile')
    const user = userEvent.setup()
    await pickFile(cvFile())
    await screen.findByText(/Your CV was read/)
    await user.click(within(screen.getByText(/Your CV was read/).closest('div') as HTMLElement).getByRole('link', { name: 'Education' }))
    await screen.findByText(/Filled from your CV: 1 row/)

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('form')).not.toBeInTheDocument()
    expect(screen.queryByText('Sample College')).not.toBeInTheDocument()
    expect(screen.getByText('Example University')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Edit Education' }))
    expect(document.querySelectorAll('[data-row]')).toHaveLength(1)
    expect(named(backend.calls, 'PUT', '/career/education')).toHaveLength(0)

    // The other sections still hold their part of the proposal.
    await user.click(screen.getByRole('link', { name: 'Overview' }))
    const result = within((await screen.findByText(/Your CV was read/)).closest('div') as HTMLElement)
    expect(result.queryByRole('link', { name: 'Education' })).not.toBeInTheDocument()
    expect(result.getByRole('link', { name: 'Personal' })).toBeInTheDocument()
  })

  it('keeps a proposal for a section that was not opened while the user moves between pages', async () => {
    stubBackend({ career: SAVED, routes: { 'POST /cv/import': reply(200, PROPOSAL) } })
    renderProfileArea('/profile')
    const user = userEvent.setup()
    await pickFile(cvFile())
    await screen.findByText(/Your CV was read/)

    await user.click(screen.getByRole('link', { name: 'Skills and languages' }))

    expect(await screen.findByText('Filled from your CV: 1 row. Review them, then press Save. Nothing is saved yet.')).toBeInTheDocument()
    const rows = Array.from(document.querySelectorAll<HTMLElement>('[data-row]'))
    expect(rows.map((row) => within(row).getByLabelText('Skill'))).toHaveLength(2)
    expect(within(rows[1] as HTMLElement).getByLabelText('Skill')).toHaveValue('Go')
    // The Languages card has nothing to review and stays in its read view.
    expect(screen.getByRole('button', { name: 'Edit Languages' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByRole('form')).toHaveLength(1))
  })
})
