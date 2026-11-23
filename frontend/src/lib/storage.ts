import type { StateStorage } from 'zustand/middleware'

/**
 * Web Storage that never throws: private windows, blocked site data and quota errors make the
 * app fall back to in-memory state instead of crashing.
 */
export function safeStorage(kind: 'local' | 'session'): StateStorage {
  const pick = (): Storage | null => {
    try {
      return kind === 'local' ? window.localStorage : window.sessionStorage
    } catch {
      return null
    }
  }
  return {
    getItem: (name) => {
      try {
        return pick()?.getItem(name) ?? null
      } catch {
        return null
      }
    },
    setItem: (name, value) => {
      try {
        pick()?.setItem(name, value)
      } catch {
        // Storage full or blocked: the value lives in memory for this session only.
      }
    },
    removeItem: (name) => {
      try {
        pick()?.removeItem(name)
      } catch {
        // Nothing to clean up when storage is unavailable.
      }
    },
  }
}
