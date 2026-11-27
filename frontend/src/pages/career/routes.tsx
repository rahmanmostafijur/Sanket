import type { ReactNode } from 'react'
import type { RouteObject } from 'react-router'
import CareerLayout from './CareerLayout'

/** The profile area: one layout with the sections inside it, each loaded when first opened. `wrap` adds the sign-in guard. */
export function profileRoute(wrap: (element: ReactNode) => ReactNode = (element) => element): RouteObject {
  return {
    path: 'profile',
    element: wrap(<CareerLayout />),
    // Shown while the section for the first page load is fetched.
    hydrateFallbackElement: <div aria-busy="true" className="h-64" />,
    children: [
      { index: true, lazy: async () => ({ Component: (await import('./ProfileOverview')).OverviewPage }) },
      { path: 'personal', lazy: async () => ({ Component: (await import('./SectionPages')).PersonalPage }) },
      { path: 'education', lazy: async () => ({ Component: (await import('./SectionPages')).EducationPage }) },
      { path: 'experience', lazy: async () => ({ Component: (await import('./SectionPages')).ExperiencePage }) },
      { path: 'skills', lazy: async () => ({ Component: (await import('./SectionPages')).SkillsPage }) },
      { path: 'accomplishments', lazy: async () => ({ Component: (await import('./SectionPages')).AccomplishmentsPage }) },
      { path: 'matching', lazy: async () => ({ Component: (await import('../profile/MatchingProfilesPage')).default }) },
    ],
  }
}
