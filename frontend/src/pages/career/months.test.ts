import { currentMonth, formatMonth, formatRange, isMonth } from './months'

describe('months', () => {
  it('accepts only YYYY-MM', () => {
    expect(isMonth('2019-07')).toBe(true)
    expect(['2019-7', '2019-13', '2019-00', '2019-07-01', 'July 2019', ''].some(isMonth)).toBe(false)
  })

  it('reads the current month from a date', () => {
    expect(currentMonth(new Date(2026, 10, 28))).toBe('2026-11')
    expect(currentMonth(new Date(2026, 0, 1))).toBe('2026-01')
  })

  it('formats a month and a range', () => {
    expect(formatMonth('2019-07')).toBe('Jul 2019')
    expect(formatMonth('soon')).toBe('soon')
    expect(formatRange('2015-09', '2019-06')).toBe('Sep 2015 – Jun 2019')
    expect(formatRange('2015-09', null)).toBe('Sep 2015')
    expect(formatRange('2019-07', null, true)).toBe('Jul 2019 – Present')
  })
})
