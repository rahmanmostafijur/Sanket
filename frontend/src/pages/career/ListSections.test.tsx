import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Education, Experience } from '@/api/types'
import { useSession } from '@/stores/session'
import { accountToken, bodyOf, emptyCareer, named, only, reply, stubBackend, stubBrowserGaps } from '@/test/careerApi'
import { preloadProfileArea, renderProfileArea } from '@/test/renderProfileArea'

const { scrollIntoView } = stubBrowserGaps()

const EDU: Education = { id: 1, institution: 'Example University', degree: 'BSc', field: 'Computer science', start: '2015-09', end: '2019-06', grade: 'First' }
const JOB: Experience = { id: 2, company: 'Example Ltd', title: 'Backend engineer', start: '2019-07', end: null, current: true, description: 'Built the billing API.' }

beforeAll(preloadProfileArea, 30_000)

beforeEach(() => {
  scrollIntoView.mockClear()
  window.localStorage.clear()
  useSession.setState({ activeProfileId: null, token: accountToken() })
})

afterEach(() => vi.unstubAllGlobals())

const month = (input: HTMLElement, value: string) => fireEvent.change(input, { target: { value } })

/** The row editors on the page, in order. */
const rows = () => Array.from(document.querySelectorAll<HTMLElement>('[data-row]'))

describe('Education', () => {
  it('lists the saved entries in a read view', async () => {
    stubBackend({ career: { education: [EDU] } })
    renderProfileArea('/profile/education')

    expect(await screen.findByText('Example University')).toBeInTheDocument()
    expect(screen.getByText('BSc, Computer science')).toBeInTheDocument()
    expect(screen.getByText('Sep 2015 – Jun 2019 · First')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit Education' })).toBeInTheDocument()
  })

  it('explains what to add when the list is empty', async () => {
    stubBackend()
    renderProfileArea('/profile/education')

    expect(await screen.findByText('No education yet')).toBeInTheDocument()
    expect(screen.getByText(/Add your degrees and courses/)).toBeInTheDocument()
  })

  it('adds a row, saves the whole list in one request without ids, and shows it', async () => {
    const backend = stubBackend({ career: { education: [EDU] } })
    renderProfileArea('/profile/education')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Education' }))
    await user.click(screen.getByRole('button', { name: 'Add education entry' }))
    const added = within(rows()[1] as HTMLElement)
    await user.type(added.getByLabelText('Institution'), '  Sample College ')
    month(added.getByLabelText('Start'), '2020-01')
    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByRole('button', { name: 'Edit Education' })).toBeInTheDocument()
    expect(bodyOf(only(backend.calls, 'PUT', '/career/education'))).toEqual({
      items: [
        { institution: 'Example University', degree: 'BSc', field: 'Computer science', start: '2015-09', end: '2019-06', grade: 'First' },
        { institution: 'Sample College', degree: '', field: '', start: '2020-01', end: null, grade: '' },
      ],
    })
    expect(screen.getByText('Sample College')).toBeInTheDocument()
    expect(screen.getByText('Jan 2020')).toBeInTheDocument()
  })

  it('removes a row and saves the rest', async () => {
    const second: Education = { ...EDU, id: 3, institution: 'Sample College' }
    const backend = stubBackend({ career: { education: [EDU, second] } })
    renderProfileArea('/profile/education')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Education' }))
    await user.click(screen.getByRole('button', { name: 'Remove education entry 1' }))
    await user.click(screen.getByRole('button', { name: /^save/i }))

    await waitFor(() => expect(named(backend.calls, 'PUT', '/career/education')).toHaveLength(1))
    expect((bodyOf(only(backend.calls, 'PUT', '/career/education')) as { items: { institution: string }[] }).items.map((item) => item.institution)).toEqual(['Sample College'])
  })

  it('discards added rows, changes and errors on Cancel without sending anything', async () => {
    const backend = stubBackend({ career: { education: [EDU] } })
    renderProfileArea('/profile/education')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Education' }))
    await user.clear(screen.getByLabelText('Institution'))
    await user.click(screen.getByRole('button', { name: 'Add education entry' }))
    await user.click(screen.getByRole('button', { name: /^save/i }))
    expect(await screen.findAllByText('Add the institution.')).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('form')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('Example University')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Edit Education' }))
    expect(rows()).toHaveLength(1)
    expect(screen.getByLabelText('Institution')).toHaveValue('Example University')
    expect(screen.queryByText('Add the institution.')).not.toBeInTheDocument()
    expect(named(backend.calls, 'PUT', '/career/education')).toHaveLength(0)
  })

  it('shows each problem on its row and field, focuses the first, and clears one when it is fixed', async () => {
    const backend = stubBackend({ career: { education: [EDU] } })
    renderProfileArea('/profile/education')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Education' }))
    await user.click(screen.getByRole('button', { name: 'Add education entry' }))
    const second = within(rows()[1] as HTMLElement)
    month(second.getByLabelText('Start'), '2020-05')
    month(second.getByLabelText('End'), '2020-01')
    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(screen.getByText('Please fix these fields: Institution (row 2), End (row 2).')).toBeInTheDocument()
    expect(second.getByLabelText('Institution')).toHaveFocus()
    expect(second.getByLabelText('Institution')).toHaveAttribute('aria-invalid', 'true')
    expect(second.getByText('The end must not be before the start.')).toBeInTheDocument()
    expect(within(rows()[0] as HTMLElement).queryByRole('alert')).not.toBeInTheDocument()
    expect(scrollIntoView).toHaveBeenCalled()
    expect(named(backend.calls, 'PUT', '/career/education')).toHaveLength(0)

    await user.type(second.getByLabelText('Institution'), 'Sample College')
    expect(screen.queryByText('Add the institution.')).not.toBeInTheDocument()
    expect(screen.getByText('Please fix this field: End (row 2).')).toBeInTheDocument()
  })

  it('maps a server 422 with a row index to that row and field', async () => {
    const second: Education = { ...EDU, id: 3, institution: 'Sample College' }
    stubBackend({
      career: { education: [EDU, second] },
      routes: {
        'PUT /career/education': reply(422, {
          error: { code: 'validation_error', message: 'invalid request', details: [{ loc: ['body', 'items', 1, 'start'], msg: 'start is not a real month' }] },
        }),
      },
    })
    renderProfileArea('/profile/education')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Education' }))
    await user.click(screen.getByRole('button', { name: /^save/i }))

    const message = await screen.findByText('start is not a real month')
    expect(message.closest('[data-field="1.start"]')).not.toBeNull()
    expect(within(rows()[1] as HTMLElement).getByLabelText('Start')).toHaveFocus()
    expect(screen.getByText('Please fix this field: Start (row 2).')).toBeInTheDocument()
    expect(within(rows()[0] as HTMLElement).queryByRole('alert')).not.toBeInTheDocument()
  })

  it('stops adding at ten rows', async () => {
    const many = Array.from({ length: 10 }, (_, i) => ({ ...EDU, id: i + 1, institution: `School ${i}` }))
    stubBackend({ career: { education: many } })
    renderProfileArea('/profile/education')

    await userEvent.setup().click(await screen.findByRole('button', { name: 'Edit Education' }))

    expect(screen.getByRole('button', { name: 'Add education entry' })).toBeDisabled()
  })
})

describe('Experience', () => {
  it('shows a current role as present and the description', async () => {
    stubBackend({ career: { experience: [JOB] } })
    renderProfileArea('/profile/experience')

    expect(await screen.findByText('Backend engineer')).toBeInTheDocument()
    expect(screen.getByText('Jul 2019 – Present')).toBeInTheDocument()
    expect(screen.getByText('Built the billing API.')).toBeInTheDocument()
  })

  it('disables and clears the end month while "Currently working here" is on', async () => {
    stubBackend({ career: { experience: [{ ...JOB, current: false, end: '2023-01' }] } })
    renderProfileArea('/profile/experience')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Experience' }))
    const end = screen.getByLabelText('End')
    expect(end).toBeEnabled()
    expect(end).toHaveValue('2023-01')
    await user.click(screen.getByRole('switch', { name: 'Currently working here' }))

    expect(end).toBeDisabled()
    expect(end).toHaveValue('')
    await user.click(screen.getByRole('switch', { name: 'Currently working here' }))
    expect(end).toBeEnabled()
    expect(end).toHaveValue('')
  })

  it('saves a current role with no end, and asks for the end otherwise', async () => {
    const backend = stubBackend({ career: { experience: [JOB] } })
    renderProfileArea('/profile/experience')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Experience' }))
    await user.click(screen.getByRole('switch', { name: 'Currently working here' }))
    await user.click(screen.getByRole('button', { name: /^save/i }))
    expect(await screen.findByText('Add a month.')).toBeInTheDocument()
    expect(screen.getByLabelText('End')).toHaveFocus()
    await user.click(screen.getByRole('switch', { name: 'Currently working here' }))
    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByRole('button', { name: 'Edit Experience' })).toBeInTheDocument()
    expect(bodyOf(only(backend.calls, 'PUT', '/career/experience'))).toEqual({
      items: [{ company: 'Example Ltd', title: 'Backend engineer', start: '2019-07', end: null, current: true, description: 'Built the billing API.' }],
    })
  })

  it('does not accept a start in the future', async () => {
    stubBackend({ career: { experience: [JOB] } })
    renderProfileArea('/profile/experience')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Experience' }))
    month(screen.getByLabelText('Start'), `${new Date().getFullYear() + 1}-01`)
    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByText('This month is in the future.')).toBeInTheDocument()
  })
})

describe('Skills and languages', () => {
  it('shows both cards, each with its own empty state and Edit button', async () => {
    stubBackend()
    renderProfileArea('/profile/skills')

    expect(await screen.findByText('No skills yet')).toBeInTheDocument()
    expect(screen.getByText('No languages yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit Skills' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit Languages' })).toBeInTheDocument()
  })

  it('replaces the skills list and leaves the languages alone', async () => {
    const backend = stubBackend({ career: { skills: [{ id: 1, name: 'Python', level: 'expert' }], languages: [{ id: 2, name: 'English', proficiency: 'native' }] } })
    renderProfileArea('/profile/skills')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Skills' }))
    await user.click(screen.getByRole('button', { name: 'Add skill' }))
    const added = within(rows()[1] as HTMLElement)
    await user.type(added.getByLabelText('Skill'), 'Go')
    await user.selectOptions(added.getByLabelText('Level'), 'advanced')
    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByRole('button', { name: 'Edit Skills' })).toBeInTheDocument()
    expect(bodyOf(only(backend.calls, 'PUT', '/career/skills'))).toEqual({ items: [{ name: 'Python', level: 'expert' }, { name: 'Go', level: 'advanced' }] })
    expect(named(backend.calls, 'PUT', '/career/languages')).toHaveLength(0)
    expect(screen.getByText('English')).toBeInTheDocument()
  })

  it('flags a repeated skill name on the second row', async () => {
    stubBackend({ career: { skills: [{ id: 1, name: 'Python', level: null }] } })
    renderProfileArea('/profile/skills')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Skills' }))
    await user.click(screen.getByRole('button', { name: 'Add skill' }))
    await user.type(within(rows()[1] as HTMLElement).getByLabelText('Skill'), 'python')
    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByText('This is already in the list.')).toBeInTheDocument()
    expect(screen.getByText('Please fix this field: Skill (row 2).')).toBeInTheDocument()
  })

  it('needs a language level', async () => {
    stubBackend()
    renderProfileArea('/profile/skills')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Languages' }))
    await user.click(screen.getByRole('button', { name: 'Add language' }))
    await user.type(screen.getByLabelText('Language'), 'German')
    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByText('Choose a level.')).toBeInTheDocument()
    expect(screen.getByLabelText('Level')).toHaveFocus()
  })
})

describe('Accomplishments', () => {
  it('saves a certification with its year as a number and a project, each by its own request', async () => {
    const backend = stubBackend()
    renderProfileArea('/profile/accomplishments')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Certifications' }))
    await user.click(screen.getByRole('button', { name: 'Add certification' }))
    await user.type(screen.getByLabelText('Name'), 'Cloud practitioner')
    await user.type(screen.getByLabelText('Issuer'), 'Example Institute')
    await user.type(screen.getByLabelText('Year'), '2022')
    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByText('Example Institute · 2022')).toBeInTheDocument()
    expect(bodyOf(only(backend.calls, 'PUT', '/career/certifications'))).toEqual({ items: [{ title: 'Cloud practitioner', issuer: 'Example Institute', year: 2022, url: '' }] })

    await user.click(screen.getByRole('button', { name: 'Edit Projects' }))
    await user.click(screen.getByRole('button', { name: 'Add project' }))
    await user.type(screen.getByLabelText('Name'), 'Crawler')
    await user.type(screen.getByLabelText('Link'), 'github.com/ada-example/crawler')
    await user.click(screen.getByRole('button', { name: /^save/i }))

    expect(await screen.findByRole('link', { name: 'Open link' })).toHaveAttribute('href', 'https://github.com/ada-example/crawler')
    expect(bodyOf(only(backend.calls, 'PUT', '/career/projects'))).toEqual({ items: [{ title: 'Crawler', description: '', url: 'github.com/ada-example/crawler' }] })
  })

  it('rejects a year out of range next to the year field', async () => {
    stubBackend({ career: emptyCareer() })
    renderProfileArea('/profile/accomplishments')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Edit Certifications' }))
    await user.click(screen.getByRole('button', { name: 'Add certification' }))
    await user.type(screen.getByLabelText('Name'), 'Old certificate')
    await user.type(screen.getByLabelText('Year'), '1900')
    await user.click(screen.getByRole('button', { name: /^save/i }))

    const message = await screen.findByText(/Use a year from 1950 to/)
    expect(message.closest('[data-field="0.year"]')).not.toBeNull()
    expect(screen.getByLabelText('Year')).toHaveFocus()
  })
})
