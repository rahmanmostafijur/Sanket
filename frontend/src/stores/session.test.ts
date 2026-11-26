import { migrateSession, useSession } from './session'

const CREDENTIAL = 'sk-test-credential-123'

function resetSession(): void {
  window.localStorage.clear()
  window.sessionStorage.clear()
  useSession.setState({ activeProfileId: null, token: null })
}

describe('migrateSession', () => {
  it('drops the removed data-source keys and any stored credential, and keeps the rest', () => {
    const stored = { mode: 'demo', apiBaseUrl: 'https://example.test', activeProfileId: 7, rememberToken: true, token: 'abc' }
    expect(migrateSession(stored)).toEqual({ activeProfileId: 7 })
  })

  it('returns an empty state when nothing usable was stored', () => {
    expect(migrateSession(null)).toEqual({})
    expect(migrateSession('broken')).toEqual({})
  })
})

describe('credential storage', () => {
  beforeEach(resetSession)
  afterAll(resetSession)

  it('keeps the credential in sessionStorage and never writes it to localStorage', () => {
    useSession.getState().setToken(`  ${CREDENTIAL}  `)
    useSession.getState().setActiveProfileId(3)

    expect(useSession.getState().token).toBe(CREDENTIAL)
    expect(window.sessionStorage.getItem('sanket.token')).toBe(CREDENTIAL)
    const persisted = window.localStorage.getItem('sanket.session')
    expect(persisted).not.toBeNull()
    expect(persisted).not.toContain(CREDENTIAL)
    expect(JSON.parse(persisted ?? '{}').state).toEqual({ activeProfileId: 3 })
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index) ?? ''
      expect(window.localStorage.getItem(key)).not.toContain(CREDENTIAL)
    }
  })

  it('removes the credential from the store and sessionStorage when cleared', () => {
    useSession.getState().setToken(CREDENTIAL)
    useSession.getState().clearToken()

    expect(useSession.getState().token).toBeNull()
    expect(window.sessionStorage.getItem('sanket.token')).toBeNull()
  })
})
