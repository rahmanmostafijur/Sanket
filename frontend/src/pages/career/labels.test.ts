import { countryName, formatYears } from './labels'

describe('countryName', () => {
  it('names a country from its code, ignoring case', () => {
    expect(countryName('de')).toBe('Germany')
    expect(countryName('BD')).toBe('Bangladesh')
  })

  it('has no name for something that is not a code', () => {
    expect(countryName('')).toBeNull()
    expect(countryName('D')).toBeNull()
    expect(countryName('Germany')).toBeNull()
  })
})

describe('formatYears', () => {
  it('rounds to one decimal and says year or years', () => {
    expect(formatYears(6.5)).toBe('6.5 years')
    expect(formatYears(1)).toBe('1 year')
    expect(formatYears(3.04)).toBe('3 years')
  })
})
