import { migrateSession } from './session'

describe('migrateSession', () => {
  it('drops the removed data-source keys and keeps the rest', () => {
    const stored = { mode: 'demo', apiBaseUrl: 'https://example.test', activeProfileId: 7, rememberToken: true, token: 'abc' }
    expect(migrateSession(stored)).toEqual({ activeProfileId: 7, rememberToken: true, token: 'abc' })
  })

  it('returns an empty state when nothing usable was stored', () => {
    expect(migrateSession(null)).toEqual({})
    expect(migrateSession('broken')).toEqual({})
  })
})
