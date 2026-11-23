import { useMemo } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { Job } from '@/api/types'
import { safeStorage } from '@/lib/storage'
import { useSession, type DataMode } from './session'

/**
 * Saved jobs of demo mode, kept in this browser with a snapshot of the job. In API mode saved
 * jobs live on the server (`/saved-jobs`, see hooks/data.ts). Entries are keyed by data mode,
 * so demo jobs never show up in API mode or the other way round.
 */
export interface SavedJob {
  job: Job
  /** ISO time it was saved. */
  savedAt: string
  /** The profile match score when it was saved, if the job had matched. */
  matchScore: number | null
}

export function savedKey(mode: DataMode, jobId: number): string {
  return `${mode}:${jobId}`
}

interface SavedState {
  items: Record<string, SavedJob>
  toggle: (job: Job, matchScore: number | null) => boolean
  remove: (jobId: number) => void
  /** Removes the saved jobs of the current data mode. */
  clear: () => void
}

const currentMode = (): DataMode => useSession.getState().mode

export const useSaved = create<SavedState>()(
  persist(
    (set, get) => ({
      items: {},
      toggle: (job, matchScore) => {
        const key = savedKey(currentMode(), job.job_id)
        if (key in get().items) {
          get().remove(job.job_id)
          return false
        }
        const entry: SavedJob = { job, savedAt: new Date().toISOString(), matchScore }
        set({ items: { ...get().items, [key]: entry } })
        return true
      },
      remove: (jobId) => {
        const key = savedKey(currentMode(), jobId)
        set({ items: Object.fromEntries(Object.entries(get().items).filter(([k]) => k !== key)) })
      },
      clear: () => {
        const prefix = `${currentMode()}:`
        set({ items: Object.fromEntries(Object.entries(get().items).filter(([k]) => !k.startsWith(prefix))) })
      },
    }),
    {
      name: 'sanket.saved',
      version: 2,
      storage: createJSONStorage(() => safeStorage('local')),
      // Version 1 did not record the data mode, so its entries cannot be attributed safely.
      migrate: () => ({ items: {} }),
    },
  ),
)

/** Saved jobs of the current data mode. */
export function useSavedEntries(): SavedJob[] {
  const mode = useSession((s) => s.mode)
  const items = useSaved((s) => s.items)
  return useMemo(() => {
    const prefix = `${mode}:`
    return Object.entries(items).flatMap(([key, entry]) => (key.startsWith(prefix) ? [entry] : []))
  }, [mode, items])
}

export function useIsSaved(jobId: number): boolean {
  const mode = useSession((s) => s.mode)
  return useSaved((s) => savedKey(mode, jobId) in s.items)
}

export function useSavedJob(jobId: number): Job | null {
  const mode = useSession((s) => s.mode)
  return useSaved((s) => s.items[savedKey(mode, jobId)]?.job ?? null)
}
