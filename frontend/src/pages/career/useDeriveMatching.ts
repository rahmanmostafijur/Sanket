import { useState } from 'react'
import { useNavigate } from 'react-router'
import { ApiError, errorMessage } from '@/api/client'
import { useMatchingDraft } from '@/hooks/career'
import { DRAFT_STATE_KEY } from '../profile/matchingDraft'

export const MATCHING_PATH = '/profile/matching'

const NOTHING_TO_USE = 'Add experience or skills to your career profile first.'

/** The 422 says what is missing; without the usual error body there is only the status to go on. */
function deriveMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 422) return error.code.startsWith('http_') ? NOTHING_TO_USE : error.message
  return errorMessage(error)
}

/**
 * Asks for a matching profile suggested by the career profile and opens the matching page with it,
 * ready to review. Nothing is created: that happens when the user presses Create profile there.
 */
export function useDeriveMatching() {
  const draft = useMatchingDraft()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const run = () => {
    if (draft.isPending) return
    setError(null)
    draft.mutate(undefined, {
      onSuccess: (suggestion) => navigate(MATCHING_PATH, { state: { [DRAFT_STATE_KEY]: suggestion } }),
      onError: (failure) => setError(deriveMessage(failure)),
    })
  }
  return { run, pending: draft.isPending, error }
}
