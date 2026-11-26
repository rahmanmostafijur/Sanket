import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { useShallow } from 'zustand/react/shallow'
import type { ApiConfig } from '@/api/client'
import { safeStorage } from '@/lib/storage'

export const DEFAULT_API_BASE: string = import.meta.env.VITE_API_BASE_URL || '/api'
const SESSION_TOKEN_KEY = 'sanket.token'
const sessionTokens = safeStorage('session')

interface SessionState {
  activeProfileId: number | null
  /** The sign-in credential. Kept in memory and sessionStorage only, never in localStorage. */
  token: string | null
  setActiveProfileId: (id: number | null) => void
  setToken: (token: string) => void
  clearToken: () => void
}

function initialToken(): string | null {
  const value = sessionTokens.getItem(SESSION_TOKEN_KEY)
  return typeof value === 'string' && value ? value : null
}

const REMOVED_KEYS = new Set(['mode', 'apiBaseUrl', 'token', 'rememberToken'])

/** Drops the data-source choice and API address, and any credential an earlier version stored. */
export function migrateSession(persisted: unknown): Partial<SessionState> {
  if (typeof persisted !== 'object' || persisted === null) return {}
  return Object.fromEntries(Object.entries(persisted).filter(([key]) => !REMOVED_KEYS.has(key))) as Partial<SessionState>
}

export const useSession = create<SessionState>()(
  persist(
    (set) => ({
      activeProfileId: null,
      token: initialToken(),
      setActiveProfileId: (id) => set({ activeProfileId: id }),
      setToken: (token) => {
        const value = token.trim()
        if (value) sessionTokens.setItem(SESSION_TOKEN_KEY, value)
        else sessionTokens.removeItem(SESSION_TOKEN_KEY)
        set({ token: value || null })
      },
      clearToken: () => {
        sessionTokens.removeItem(SESSION_TOKEN_KEY)
        set({ token: null })
      },
    }),
    {
      name: 'sanket.session',
      version: 3,
      storage: createJSONStorage(() => safeStorage('local')),
      migrate: migrateSession,
      // Only non-secret state reaches localStorage; the credential never does.
      partialize: (state) => ({ activeProfileId: state.activeProfileId }),
      merge: (persisted, current) => {
        const saved = (persisted ?? {}) as Partial<SessionState>
        return { ...current, ...saved, token: current.token }
      },
    },
  ),
)

export function useApiConfig(): ApiConfig {
  return useSession(useShallow((s) => ({ baseUrl: DEFAULT_API_BASE, token: s.token })))
}
