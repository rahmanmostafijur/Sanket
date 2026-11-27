import { ApiError } from '@/api/client'
import { checkCvFile, cvImportMessage } from './cvFile'

describe('checkCvFile', () => {
  it('accepts PDF and DOCX in any letter case', () => {
    expect(checkCvFile(new File(['x'], 'cv.PDF'))).toBeNull()
    expect(checkCvFile(new File(['x'], 'cv.docx'))).toBeNull()
  })

  it('rejects other types', () => {
    expect(checkCvFile(new File(['x'], 'cv.doc'))).toBe('Only PDF and DOCX files are supported.')
    expect(checkCvFile(new File(['x'], 'cv.pdf.txt'))).toBe('Only PDF and DOCX files are supported.')
  })

  it('rejects a file over 5 MB but accepts exactly 5 MB', () => {
    const file = (size: number) => Object.defineProperty(new File(['x'], 'cv.pdf'), 'size', { value: size })
    expect(checkCvFile(file(5 * 1024 * 1024))).toBeNull()
    expect(checkCvFile(file(5 * 1024 * 1024 + 1))).toBe('That file is larger than 5 MB.')
  })
})

describe('cvImportMessage', () => {
  const failure = (status: number, retryAfterMs: number | null = null, message = 'server text') => new ApiError(status, 'x', message, null, retryAfterMs)

  it('explains each failure', () => {
    expect(cvImportMessage(failure(413))).toBe('That file is larger than 5 MB.')
    expect(cvImportMessage(failure(422, null, 'The PDF has no text; it looks scanned.'))).toBe('The PDF has no text; it looks scanned.')
    expect(cvImportMessage(failure(429, 12_000))).toBe('Too many imports. Try again in 12 seconds.')
    expect(cvImportMessage(failure(429, 1_000))).toBe('Too many imports. Try again in 1 second.')
    expect(cvImportMessage(failure(503, 150_000))).toBe('The language model is unavailable right now (quota). Try again in 3 minutes.')
    expect(cvImportMessage(failure(503))).toBe('The language model is unavailable right now (quota). Try again later.')
  })

  it('falls back to one generic line for anything else', () => {
    expect(cvImportMessage(failure(502))).toBe('Could not read the CV. Try again.')
    expect(cvImportMessage(new ApiError(0, 'network_error', 'Could not connect'))).toBe('Could not read the CV. Try again.')
    expect(cvImportMessage(new Error('boom'))).toBe('Could not read the CV. Try again.')
  })
})
