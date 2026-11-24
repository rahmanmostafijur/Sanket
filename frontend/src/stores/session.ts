import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { useShallow } from 'zustand/react/shallow'
import type { ApiConfig } from '@/api/client'
import { safeStorage } from '@/lib/storage'

/** `api` reads the Sanket API; `demo` reads clearly labelled sample data in the browser. */
export type DataMode = 'api' | 'demo'

export const DEFAULT_API_BASE: string = import.meta.env.VITE_API_BASE_URL || '/api'
const SESSION_TOKEN_KEY = 'sanket.token'
const sessionTokens = safeStorage('session')

interface SessionState {
  mode: DataMode
  apiBaseUrl: string
  activeProfileId: number | null
  token: string | null
  /** Keep the credential in localStorage across browser restarts (otherwise this tab only). */
  rememberToken: boolean
  setMode: (mode: DataMode) => void
  setApiBaseUrl: (url: string) => void
  setActiveProfileId: (id: number | null) => void
  setToken: (token: string, remember: boolean) => void
  clearToken: () => void
}

function initialToken(): string | null {
  const value = sessionTokens.getItem(SESSION_TOKEN_KEY)
  return typeof value === 'string' && value ? value : null
}

export const useSession = create<SessionState>()(
  persist(
    (set) => ({
      mode: 'api',
      apiBaseUrl: DEFAULT_API_BASE,
      activeProfileId: null,
      token: initialToken(),
      rememberToken: false,
      setMode: (mode) => set({ mode }),
      setApiBaseUrl: (url) => set({ apiBaseUrl: url.trim() || DEFAULT_API_BASE }),
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
      version: 1,
      storage: createJSONStorage(() => safeStorage('local')),
      // The credential is written to localStorage only when the user asked to remember it.
      partialize: (state) => ({
        mode: state.mode,
        apiBaseUrl: state.apiBaseUrl,
        activeProfileId: state.activeProfileId,
        rememberToken: state.rememberToken,
        ...(state.rememberToken ? { token: state.token } : {}),
      }),
      merge: (persisted, current) => {
        const saved = (persisted ?? {}) as Partial<SessionState>
        // The data-source switch only exists in development builds, so a stored demo choice must not stick in production.
        const mode: DataMode = import.meta.env.DEV ? (saved.mode ?? current.mode) : 'api'
        return { ...current, ...saved, mode, token: saved.token ?? current.token }
      },
    },
  ),
)

export function useApiConfig(): ApiConfig {
  return useSession(useShallow((s) => ({ baseUrl: s.apiBaseUrl, token: s.token })))
}
