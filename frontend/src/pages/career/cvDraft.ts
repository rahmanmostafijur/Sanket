import { createContext, useContext } from 'react'
import type { CareerSectionKey, CvProposal } from '@/api/types'

/**
 * What a CV import proposed and no section has taken yet. It lives in the profile layout, so it
 * outlives the pages inside it; nothing in it is saved until the user saves a section.
 */
export interface CvDraft {
  proposal: CvProposal | null
  receive: (proposal: CvProposal) => void
  /** A section took its part, or the user turned it away: it is not offered again. */
  clear: (section: CareerSectionKey) => void
}

export const CvDraftContext = createContext<CvDraft | null>(null)

export function useCvDraft(): CvDraft {
  const draft = useContext(CvDraftContext)
  if (!draft) throw new Error('useCvDraft must be used inside the profile layout')
  return draft
}
