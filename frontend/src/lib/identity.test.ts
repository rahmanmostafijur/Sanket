import { describeIdentity, firstName, withDisplayName } from './identity'

function jwt(claims: Record<string, unknown>): string {
  return `eyJhbGciOiJIUzI1NiJ9.${btoa(JSON.stringify(claims)).replace(/=+$/, '')}.signature`
}

describe('describeIdentity', () => {
  it('names an account by the email in its token', () => {
    expect(describeIdentity(jwt({ sub: 'user:1', email: 'ada@example.com' }))).toEqual({ name: 'ada@example.com', initials: 'AE', kind: 'jwt' })
  })

  it('labels an API key without any of its digits', () => {
    expect(describeIdentity('sk_live_1234567890')).toEqual({ name: 'API key', initials: 'AK', kind: 'api_key' })
  })

  it('has nothing to show without a token', () => {
    expect(describeIdentity(null).kind).toBe('none')
  })
})

describe('withDisplayName', () => {
  const account = describeIdentity(jwt({ email: 'ada@example.com' }))

  it('puts the full name in place of the email', () => {
    expect(withDisplayName(account, ' Ada Example ')).toMatchObject({ name: 'Ada Example', initials: 'AE' })
  })

  it('keeps the email when there is no full name', () => {
    expect(withDisplayName(account, '')).toBe(account)
    expect(withDisplayName(account, undefined)).toBe(account)
  })

  it('never renames an API key', () => {
    const key = describeIdentity('sk_live_1234567890')
    expect(withDisplayName(key, 'Ada Example')).toBe(key)
  })

  it('greets by first name, and not at all by an email', () => {
    expect(firstName(withDisplayName(account, 'Ada Example'))).toBe('Ada')
    expect(firstName(account)).toBeNull()
  })
})
