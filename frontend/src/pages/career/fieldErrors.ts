import { ApiError } from '@/api/client'

/** Messages by field. A personal field is keyed by its name, a list row's field by "<row index>.<name>". */
export type FieldErrors = Record<string, string>

export interface FieldInfo {
  key: string
  label: string
}

const ROW_KEY = /^(\d+)\.(.+)$/

export const rowKey = (index: number, field: string): string => `${index}.${field}`

function parts(key: string): { row: number | null; field: string } {
  const match = ROW_KEY.exec(key)
  return match ? { row: Number(match[1]), field: match[2] ?? '' } : { row: null, field: key }
}

/**
 * The fields a 422 points at, with the server's wording. The path ends in the field name; for a
 * list it holds the row index before it (["body", "items", 2, "start"]). Errors about the whole
 * body or a field this form does not have are left out.
 */
export function errorsFromServer(error: unknown, fields: readonly FieldInfo[], list: boolean): FieldErrors {
  const errors: FieldErrors = {}
  if (!(error instanceof ApiError)) return errors
  const known = new Set(fields.map((field) => field.key))
  for (const detail of error.details) {
    const loc = detail.loc ?? []
    const field = loc[loc.length - 1]
    if (typeof field !== 'string' || !detail.msg || !known.has(field)) continue
    if (!list) {
      errors[field] = detail.msg
      continue
    }
    const row = loc.find((part): part is number => typeof part === 'number')
    if (row !== undefined) errors[rowKey(row, field)] = detail.msg
  }
  return errors
}

/** The keys of `errors` in page order: by row, then by the order of the fields in a row. */
function inPageOrder(errors: FieldErrors, fields: readonly FieldInfo[]): string[] {
  const order = fields.map((field) => field.key)
  return Object.keys(errors).sort((a, b) => {
    const left = parts(a)
    const right = parts(b)
    return (left.row ?? 0) - (right.row ?? 0) || order.indexOf(left.field) - order.indexOf(right.field)
  })
}

export function firstInvalid(errors: FieldErrors, fields: readonly FieldInfo[]): string | null {
  return inPageOrder(errors, fields)[0] ?? null
}

/** One short line for the top of an editor, or null when nothing is wrong. */
export function errorSummary(errors: FieldErrors, fields: readonly FieldInfo[]): string | null {
  const keys = inPageOrder(errors, fields)
  if (!keys.length) return null
  const labels = new Map(fields.map((field) => [field.key, field.label]))
  const names = keys.map((key) => {
    const { row, field } = parts(key)
    const label = labels.get(field) ?? field
    return row === null ? label : `${label} (row ${row + 1})`
  })
  return `Please fix ${names.length === 1 ? 'this field' : 'these fields'}: ${names.join(', ')}.`
}

/** The errors left after the field `key` got a new value. Returns the same object when nothing changed. */
export function withoutError(errors: FieldErrors, key: string): FieldErrors {
  if (!(key in errors)) return errors
  const next = { ...errors }
  delete next[key]
  return next
}
