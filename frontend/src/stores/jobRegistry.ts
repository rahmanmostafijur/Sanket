import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { Job } from '@/api/types'
import { safeStorage } from '@/lib/storage'

/** Jobs this tab has seen. The detail page shows them while `GET /jobs/{id}` loads (kept in sessionStorage, so a reload still works). */
const MAX_JOBS = 400

const keyOf = (jobId: number): string => String(jobId)

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
        const current = get().jobs
        const fresh = incoming.filter((job) => current[keyOf(job.job_id)] !== job)
        if (fresh.length === 0) return
        const freshKeys = new Set(fresh.map((job) => keyOf(job.job_id)))
        // String keys keep insertion order, so dropping from the front evicts the oldest.
        const kept = Object.entries(current).filter(([key]) => !freshKeys.has(key))
        const merged = [...kept, ...fresh.map((job) => [keyOf(job.job_id), job] as const)]
        set({ jobs: Object.fromEntries(merged.slice(-MAX_JOBS)) })
      },
    }),
    {
      name: 'sanket.jobs',
      version: 3,
      storage: createJSONStorage(() => safeStorage('session')),
      migrate: () => ({ jobs: {} }),
    },
  ),
)

export function useRegisteredJob(jobId: number): Job | null {
  return useJobRegistry((s) => s.jobs[keyOf(jobId)] ?? null)
}
