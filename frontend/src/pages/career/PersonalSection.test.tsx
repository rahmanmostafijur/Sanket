import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CareerPersonal } from '@/api/types'
import { useSession } from '@/stores/session'
import { useToasts } from '@/stores/toasts'
import { accountToken, bodyOf, emptyCareer, named, only, reply, stubBackend, stubBrowserGaps, type Reply } from '@/test/careerApi'
import { preloadProfileArea, renderProfileArea } from '@/test/renderProfileArea'

const { scrollIntoView } = stubBrowserGaps()

const PERSONAL: CareerPersonal = {
  full_name: 'Ada Example',
  headline: 'Backend engineer',
  summary: 'Builds APIs.',
  country: 'DE',
  city: 'Berlin',
  github_url: 'https://github.com/ada-example',
  linkedin_url: '',
  portfolio_url: 'ada.example.com',
  availability: 'open_to_offers',
}

beforeAll(preloadProfileArea, 30_000)

beforeEach(() => {
  scrollIntoView.mockClear()
  window.localStorage.clear()
  useToasts.setState({ toasts: [] })
  useSession.setState({ activeProfileId: null, token: accountToken() })
})

afterEach(() => vi.unstubAllGlobals())

async function openEditor() {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Edit Personal' }))
  return user
}

describe('Personal: read view', () => {
  it('shows the saved details, the country name and the links, with an Edit button', async () => {
    stubBackend({ career: { personal: PERSONAL } })
    renderProfileArea('/profile/personal')

    expect(await screen.findByText('Ada Example')).toBeInTheDocument()
    expect(screen.getByText('Backend engineer')).toBeInTheDocument()
    expect(screen.getByText('Berlin, Germany (DE)')).toBeInTheDocument()
    expect(screen.getByText('Open to offers')).toBeInTheDocument()
    expect(screen.getByText('Builds APIs.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'GitHub' })).toHaveAttribute('href', 'https://github.com/ada-example')
    expect(screen.getByRole('link', { name: 'Portfolio' })).toHaveAttribute('href', 'https://ada.example.com')
    expect(screen.queryByRole('link', { name: 'LinkedIn' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit Personal' })).toBeInTheDocument()
    expect(screen.queryByRole('form')).not.toBeInTheDocument()
  })

  it('explains what to add when nothing is saved yet', async () => {
    stubBackend()
    renderProfileArea('/profile/personal')

    expect(await screen.findByText('No personal details yet')).toBeInTheDocument()
    expect(screen.getByText(/Add your name, a headline, a short summary/)).toBeInTheDocument()
  })

  it('shows a loading state, then an error with a retry that works', async () => {
    let attempts = 0
    stubBackend({
      routes: {
        'GET /career': () => (++attempts === 1 ? reply(500, { error: { code: 'boom', message: 'The server broke' } }) : reply(200, { ...emptyCareer(), personal: PERSONAL })),
      },
    })
    renderProfileArea('/profile/personal')

    expect(await screen.findByText('The server broke')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Ada Example')).toBeInTheDocument()
  })

  it('says there is no career profile for a credential that is not an account, and keeps the matching link', async () => {
    stubBackend({ routes: { 'GET /career': reply(404, { error: { code: 'not_found', message: 'this credential has no account' } }) } })
    renderProfileArea('/profile/personal')

    expect(await screen.findByText('No career profile for this sign-in')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to matching profiles' })).toHaveAttribute('href', '/profile/matching')
  })
})

describe('Personal: editing', () => {
  it('opens an editor with the saved values and a Save and a visible secondary Cancel button', async () => {
    stubBackend({ career: { personal: PERSONAL } })
    renderProfileArea('/profile/personal')
    await openEditor()

    expect(screen.getByLabelText('Full name')).toHaveValue('Ada Example')
    expect(screen.getByLabelText('Country')).toHaveValue('DE')
    expect(screen.getByText('Germany')).toBeInTheDocument()
    expect(screen.getByLabelText('Availability')).toHaveValue('open_to_offers')
    expect(screen.getByRole('button', { name: /^save/i })).toBeEnabled()
    const cancel = screen.getByRole('button', { name: 'Cancel' })
    expect(cancel).toBeEnabled()
    expect(cancel.className).toContain('bg-elevated')
  })

  it('discards changes and every error on Cancel and shows the read view again', async () => {
    const backend = stubBackend({ career: { personal: PERSONAL } })
    renderProfileArea('/profile/personal')
    const user = await openEditor()

    await user.clear(screen.getByLabelText('Full name'))
    await user.type(screen.getByLabelText('Full name'), 'Someone Else')
    await user.clear(screen.getByLabelText('GitHub'))
    await user.type(screen.getByLabelText('GitHub'), 'https://example.com/x')
    await user.click(screen.getByRole('button', { name: /^save/i }))
    expect(await screen.findByText('Use a github.com address.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('form')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('Ada Example')).toBeInTheDocument()
    expect(screen.queryByText('Someone Else')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Edit Personal' }))
    expect(screen.getByLabelText('Full name')).toHaveValue('Ada Example')
    expect(screen.getByLabelText('GitHub')).toHaveValue('https://github.com/ada-example')
    expect(screen.queryByText('Use a github.com address.')).not.toBeInTheDocument()
    expect(named(backend.calls, 'PUT', '/career/personal')).toHaveLength(0)
  })

  it('shows the problem next to its field, marks it invalid, focuses it, summarises on top, and clears it once fixed', async () => {
    const backend = stubBackend({ career: { personal: PERSONAL } })
    renderProfileArea('/profile/personal')
    const user = await openEditor()

    await user.clear(screen.getByLabelText('LinkedIn'))
    await user.type(screen.getByLabelText('LinkedIn'), 'github.com/ada')
    await user.clear(screen.getByLabelText('Portfolio'))
    await user.type(screen.getByLabelText('Portfolio'), 'not a link')
    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(screen.getByText('Please fix these fields: LinkedIn, Portfolio.')).toBeInTheDocument()
    const linkedin = screen.getByLabelText('LinkedIn')
    expect(linkedin).toHaveFocus()
    expect(linkedin).toHaveAttribute('aria-invalid', 'true')
    expect(linkedin.closest('[data-field="linkedin_url"]')).toHaveTextContent('Use a linkedin.com address.')
    expect(scrollIntoView).toHaveBeenCalled()
    expect(named(backend.calls, 'PUT', '/career/personal')).toHaveLength(0)

    await user.clear(linkedin)
    await user.type(linkedin, 'linkedin.com/in/ada')
    expect(screen.queryByText('Use a linkedin.com address.')).not.toBeInTheDocument()
    expect(screen.getByText('Please fix this field: Portfolio.')).toBeInTheDocument()
  })

  it('sends every personal field, trimmed and with the country upper-cased, and shows the saved details', async () => {
    const backend = stubBackend({ career: { personal: PERSONAL } })
    renderProfileArea('/profile/personal')
    const user = await openEditor()

    await user.clear(screen.getByLabelText('Headline'))
    await user.type(screen.getByLabelText('Headline'), '  Staff engineer ')
    await user.clear(screen.getByLabelText('Country'))
    await user.type(screen.getByLabelText('Country'), 'bd')
    await user.clear(screen.getByLabelText('City'))
    await user.selectOptions(screen.getByLabelText('Availability'), 'immediately')
    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByRole('button', { name: 'Edit Personal' })).toBeInTheDocument()
    expect(bodyOf(only(backend.calls, 'PUT', '/career/personal'))).toEqual({ ...PERSONAL, headline: 'Staff engineer', country: 'BD', city: '', availability: 'immediately' })
    expect(screen.getByText('Staff engineer')).toBeInTheDocument()
    expect(screen.getByText('Available immediately')).toBeInTheDocument()
    expect(screen.queryByRole('form')).not.toBeInTheDocument()
  })

  it('puts the server complaint on the field the 422 names', async () => {
    stubBackend({
      career: { personal: PERSONAL },
      routes: { 'PUT /career/personal': reply(422, { error: { code: 'validation_error', message: 'invalid request', details: [{ loc: ['body', 'full_name'], msg: 'must not contain links' }] } }) },
    })
    renderProfileArea('/profile/personal')
    const user = await openEditor()

    await user.type(screen.getByLabelText('Full name'), ' Jr')
    await user.click(screen.getByRole('button', { name: /^save/i }))

    const message = await screen.findByText('must not contain links')
    expect(message.closest('[data-field="full_name"]')).not.toBeNull()
    expect(screen.getByLabelText('Full name')).toHaveFocus()
    expect(screen.getByText('Please fix this field: Full name.')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Full name'), 'x')
    expect(screen.queryByText('must not contain links')).not.toBeInTheDocument()
  })

  it('shows a failure no field owns on top and stays in the editor', async () => {
    stubBackend({ career: { personal: PERSONAL }, routes: { 'PUT /career/personal': reply(500, { error: { code: 'boom', message: 'Could not save right now' } }) } })
    renderProfileArea('/profile/personal')
    const user = await openEditor()

    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByText('Could not save right now')).toBeInTheDocument()
    expect(screen.getByRole('form')).toBeInTheDocument()
  })

  it('disables Save and Cancel while saving', async () => {
    let finish: (value: Reply) => void = () => undefined
    stubBackend({ career: { personal: PERSONAL }, routes: { 'PUT /career/personal': () => new Promise<Reply>((resolve) => (finish = resolve)) } })
    renderProfileArea('/profile/personal')
    const user = await openEditor()

    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByRole('button', { name: /saving/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    finish(reply(200, PERSONAL))
    expect(await screen.findByRole('button', { name: 'Edit Personal' })).toBeInTheDocument()
  })

  it('tells the user the details were saved', async () => {
    stubBackend({ career: { personal: PERSONAL } })
    renderProfileArea('/profile/personal')
    const user = await openEditor()

    await user.click(screen.getByRole('button', { name: /^save/i }))

    await waitFor(() => expect(useToasts.getState().toasts.map((t) => t.title)).toContain('Personal details saved'))
  })
})

describe('Personal: the sidebar name', () => {
  it('changes at once after the full name is saved', async () => {
    stubBackend({ career: { personal: { ...PERSONAL, full_name: '' } } })
    renderProfileArea('/profile/personal', { sidebar: true })
    const user = await openEditor()
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(await within(nav).findByText('ada@example.com')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Full name'), 'Ada Example')
    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await within(nav).findByText('Ada Example')).toBeInTheDocument()
    expect(within(nav).queryByText('ada@example.com')).not.toBeInTheDocument()
  })
})
