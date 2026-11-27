import { ApiError } from '@/api/client'
import { errorSummary, errorsFromServer, firstInvalid, rowKey, withoutError, type FieldInfo } from './fieldErrors'

const FIELDS: FieldInfo[] = [
  { key: 'institution', label: 'Institution' },
  { key: 'start', label: 'Start' },
  { key: 'end', label: 'End' },
]

function invalid(...details: { loc: (string | number)[]; msg: string }[]): ApiError {
  return new ApiError(422, 'validation_error', 'invalid', null, null, details)
}

describe('errorsFromServer', () => {
  it('maps a list detail to its row and field', () => {
    const error = invalid({ loc: ['body', 'items', 2, 'start'], msg: 'bad month' }, { loc: ['body', 'items', 0, 'institution'], msg: 'too long' })

    expect(errorsFromServer(error, FIELDS, true)).toEqual({ '2.start': 'bad month', '0.institution': 'too long' })
  })

  it('maps a plain detail to its field name', () => {
    expect(errorsFromServer(invalid({ loc: ['body', 'institution'], msg: 'bad' }), FIELDS, false)).toEqual({ institution: 'bad' })
  })

  it('leaves out unknown fields, errors about the whole body, rows without an index and non-API errors', () => {
    const error = invalid({ loc: ['body', 'items', 1, 'nope'], msg: 'x' }, { loc: ['body', 'items'], msg: 'whole' }, { loc: ['body', 'start'], msg: 'no row' })

    expect(errorsFromServer(error, FIELDS, true)).toEqual({})
    expect(errorsFromServer(new Error('boom'), FIELDS, true)).toEqual({})
  })
})

describe('firstInvalid and errorSummary', () => {
  const errors = { [rowKey(2, 'institution')]: 'a', [rowKey(1, 'end')]: 'b', [rowKey(1, 'start')]: 'c' }

  it('goes by row, then by the order of the fields', () => {
    expect(firstInvalid(errors, FIELDS)).toBe('1.start')
    expect(firstInvalid({}, FIELDS)).toBeNull()
  })

  it('names each field with its row, in page order', () => {
    expect(errorSummary(errors, FIELDS)).toBe('Please fix these fields: Start (row 2), End (row 2), Institution (row 3).')
    expect(errorSummary({ institution: 'a' }, FIELDS)).toBe('Please fix this field: Institution.')
    expect(errorSummary({}, FIELDS)).toBeNull()
  })
})

describe('withoutError', () => {
  it('drops one error and returns the same object when there is none to drop', () => {
    const errors = { a: '1', b: '2' }

    expect(withoutError(errors, 'a')).toEqual({ b: '2' })
    expect(withoutError(errors, 'c')).toBe(errors)
  })
})
