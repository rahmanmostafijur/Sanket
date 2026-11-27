import { ApiError } from '@/api/client'
import { retrySeconds } from '@/lib/auth'

export const CV_MAX_BYTES = 5 * 1024 * 1024
export const CV_ACCEPT = '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document'

export const CV_PRIVACY_NOTE = 'Your CV text is sent to the language-model provider to read it. The file and its text are not stored.'

/** Error text for a file that must not be sent, or null. The server still checks the content. */
export function checkCvFile(file: File): string | null {
  if (!/\.(pdf|docx)$/i.test(file.name)) return 'Only PDF and DOCX files are supported.'
  if (file.size > CV_MAX_BYTES) return 'That file is larger than 5 MB.'
  return null
}

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? '' : 's'}`
}

/** A human message for a failed import. */
export function cvImportMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Could not read the CV. Try again.'
  const seconds = retrySeconds(error.retryAfterMs)
  switch (error.status) {
    case 413:
      return 'That file is larger than 5 MB.'
    case 422:
      return error.message || 'Could not read that file. Use a text-based PDF or DOCX.'
    case 429:
      return seconds === null ? 'Too many imports. Try again in a moment.' : `Too many imports. Try again in ${plural(seconds, 'second')}.`
    case 503:
      return seconds === null
        ? 'The language model is unavailable right now (quota). Try again later.'
        : `The language model is unavailable right now (quota). Try again in ${plural(Math.ceil(seconds / 60), 'minute')}.`
    default:
      return 'Could not read the CV. Try again.'
  }
}
