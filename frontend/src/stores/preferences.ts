import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { safeStorage } from '@/lib/storage'

export type ResultsView = 'list' | 'grid'
export type MotionPreference = 'system' | 'reduced'

const MAX_RECENT_SEARCHES = 6

interface PreferencesState {
  view: ResultsView
  sidebarCollapsed: boolean
  /** Toast when a live match arrives. */
  notifyOnMatch: boolean
  motion: MotionPreference
  recentSearches: string[]
  setView: (view: ResultsView) => void
  toggleSidebar: () => void
  setNotifyOnMatch: (value: boolean) => void
  setMotion: (value: MotionPreference) => void
  addRecentSearch: (query: string) => void
  clearRecentSearches: () => void
}

export const usePreferences = create<PreferencesState>()(
  persist(
    (set, get) => ({
      view: 'list',
      sidebarCollapsed: false,
      notifyOnMatch: true,
      motion: 'system',
      recentSearches: [],
      setView: (view) => set({ view }),
      toggleSidebar: () => set({ sidebarCollapsed: !get().sidebarCollapsed }),
      setNotifyOnMatch: (notifyOnMatch) => set({ notifyOnMatch }),
      setMotion: (motion) => set({ motion }),
      addRecentSearch: (query) => {
        const value = query.trim()
        if (!value) return
        const rest = get().recentSearches.filter((item) => item.toLowerCase() !== value.toLowerCase())
        set({ recentSearches: [value, ...rest].slice(0, MAX_RECENT_SEARCHES) })
      },
      clearRecentSearches: () => set({ recentSearches: [] }),
    }),
    { name: 'sanket.prefs', version: 1, storage: createJSONStorage(() => safeStorage('local')) },
  ),
)
