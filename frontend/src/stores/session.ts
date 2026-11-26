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
  token: string | null
  /** Keep the credential in localStorage across browser restarts (otherwise this tab only). */
  rememberToken: boolean
  setActiveProfileId: (id: number | null) => void
  setToken: (token: string, remember: boolean) => void
  clearToken: () => void
}

function initialToken(): string | null {
  const value = sessionTokens.getItem(SESSION_TOKEN_KEY)
  return typeof value === 'string' && value ? value : null
}

const REMOVED_KEYS = new Set(['mode', 'apiBaseUrl'])

/** Drops the data-source choice and API address that earlier versions stored. */
export function migrateSession(persisted: unknown): Partial<SessionState> {
  if (typeof persisted !== 'object' || persisted === null) return {}
  return Object.fromEntries(Object.entries(persisted).filter(([key]) => !REMOVED_KEYS.has(key))) as Partial<SessionState>
}

export const useSession = create<SessionState>()(
  persist(
    (set) => ({
      activeProfileId: null,
      token: initialToken(),
      rememberToken: false,
      setActiveProfileId: (id) => set({ activeProfileId: id }),
      setToken: (token, remember) => {
        const value = token.trim()
        if (remember) sessionTokens.removeItem(SESSION_TOKEN_KEY)
        else sessionTokens.setItem(SESSION_TOKEN_KEY, value)
        set({ token: value || null, rememberToken: remember })
      },
      clearToken: () => {
        sessionTokens.removeItem(SESSION_TOKEN_KEY)
        set({ token: null, rememberToken: false })
      },
    }),
    {
      name: 'sanket.session',
      version: 2,
      storage: createJSONStorage(() => safeStorage('local')),
      migrate: migrateSession,
      // The credential is written to localStorage only when the user asked to remember it.
      partialize: (state) => ({
        activeProfileId: state.activeProfileId,
        rememberToken: state.rememberToken,
        ...(state.rememberToken ? { token: state.token } : {}),
      }),
      merge: (persisted, current) => {
        const saved = (persisted ?? {}) as Partial<SessionState>
        return { ...current, ...saved, token: saved.token ?? current.token }
      },
    },
  ),
)

export function useApiConfig(): ApiConfig {
  return useSession(useShallow((s) => ({ baseUrl: DEFAULT_API_BASE, token: s.token })))
}
