import { useState } from 'react'
import type { CvProposal } from '@/api/types'
import { useImportCv } from '@/hooks/data'
import { checkCvFile, cvImportMessage } from './cvProposal'

/** Runs a CV import: checks the file here first, then asks the API to read it. Nothing is saved. */
export function useCvImport(onProposal: (proposal: CvProposal) => void) {
  const importCv = useImportCv()
  const [error, setError] = useState<string | null>(null)
  const importFile = (file: File) => {
    if (importCv.isPending) return
    const problem = checkCvFile(file)
    setError(problem)
    if (problem) return
    importCv.mutate(file, { onSuccess: onProposal, onError: (failure) => setError(cvImportMessage(failure)) })
  }
  /** Forgets the last failure, for when the form is cancelled. */
  const reset = () => setError(null)
  return { importFile, pending: importCv.isPending, error, reset }
}

export type CvImport = ReturnType<typeof useCvImport>
