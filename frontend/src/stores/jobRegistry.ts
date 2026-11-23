import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { Job } from '@/api/types'
import { safeStorage } from '@/lib/storage'
import { useSession, type DataMode } from './session'

/**
 * Jobs this tab has seen. The detail page shows them while `GET /jobs/{id}` loads, and demo
 * live-feed jobs come only from here (kept in sessionStorage, so a reload still works). Keys carry the
 * data mode, so a demo job can never stand in for a real one with the same id.
 */
const MAX_JOBS = 400

const keyOf = (mode: DataMode, jobId: number): string => `${mode}:${jobId}`

interface JobRegistryState {
  /** Insertion order is recency order: a re-seen job moves to the end. */
  jobs: Record<string, Job>
  remember: (jobs: readonly Job[]) => void
}

export const useJobRegistry = create<JobRegistryState>()(
  persist(
    (set, get) => ({
      jobs: {},
      remember: (incoming) => {
        const mode = useSession.getState().mode
        const current = get().jobs
        const fresh = incoming.filter((job) => current[keyOf(mode, job.job_id)] !== job)
        if (fresh.length === 0) return
        const freshKeys = new Set(fresh.map((job) => keyOf(mode, job.job_id)))
        // String keys keep insertion order, so dropping from the front evicts the oldest.
        const kept = Object.entries(current).filter(([key]) => !freshKeys.has(key))
        const merged = [...kept, ...fresh.map((job) => [keyOf(mode, job.job_id), job] as const)]
        set({ jobs: Object.fromEntries(merged.slice(-MAX_JOBS)) })
      },
    }),
    {
      name: 'sanket.jobs',
      version: 2,
      storage: createJSONStorage(() => safeStorage('session')),
      migrate: () => ({ jobs: {} }),
    },
  ),
)

export function useRegisteredJob(jobId: number): Job | null {
  const mode = useSession((s) => s.mode)
  return useJobRegistry((s) => s.jobs[keyOf(mode, jobId)] ?? null)
}
