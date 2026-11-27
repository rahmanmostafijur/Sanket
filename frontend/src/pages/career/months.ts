/** Months are "YYYY-MM" strings, which sort the same as the dates they stand for. */
const MONTH_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function isMonth(value: string): boolean {
  return MONTH_PATTERN.test(value)
}

export function currentMonth(now: Date = new Date()): string {
  return `${String(now.getFullYear()).padStart(4, '0')}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

/** "2019-07" as "Jul 2019"; anything that is not a month is returned as it is. */
export function formatMonth(value: string): string {
  if (!isMonth(value)) return value
  return `${MONTH_NAMES[Number(value.slice(5)) - 1]} ${value.slice(0, 4)}`
}

/** "Jul 2019 – Present", "Sep 2015 – Jun 2019" or just the start when there is no end. */
export function formatRange(start: string, end: string | null, current = false): string {
  if (current) return `${formatMonth(start)} – Present`
  return end ? `${formatMonth(start)} – ${formatMonth(end)}` : formatMonth(start)
}
