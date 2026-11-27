import { useMemo, useState, type ReactNode } from 'react'
import type { CareerSectionKey, CvProposal } from '@/api/types'
import { withoutSection } from './cvMerge'
import { CvDraftContext, type CvDraft } from './cvDraft'

export function CvDraftProvider({ children }: { children: ReactNode }) {
  const [proposal, setProposal] = useState<CvProposal | null>(null)
  const value = useMemo<CvDraft>(
    () => ({
      proposal,
      receive: setProposal,
      clear: (section: CareerSectionKey) => setProposal((current) => (current ? withoutSection(current, section) : current)),
    }),
    [proposal],
  )
  return <CvDraftContext.Provider value={value}>{children}</CvDraftContext.Provider>
}
