import { NavLink, Outlet } from 'react-router'
import { PageHeader } from '@/components/layout/PageHeader'
import { cn } from '@/lib/cn'
import { CvDraftProvider } from './CvDraftProvider'

const TABS: readonly { to: string; label: string; end?: boolean }[] = [
  { to: '/profile', label: 'Overview', end: true },
  { to: '/profile/personal', label: 'Personal' },
  { to: '/profile/education', label: 'Education' },
  { to: '/profile/experience', label: 'Experience' },
  { to: '/profile/skills', label: 'Skills and languages' },
  { to: '/profile/accomplishments', label: 'Accomplishments' },
  { to: '/profile/matching', label: 'Matching profiles' },
]

/** The profile area: a header, a row of section links that scrolls sideways on a phone, and the section itself. */
export default function CareerLayout() {
  return (
    <CvDraftProvider>
      <div className="mx-auto max-w-[980px]">
        <PageHeader title="Profile" description="Your career profile is private to you. It is never shown to anyone and cannot be downloaded." className="pb-4" />
        <nav aria-label="Profile sections" className="-mx-4 mb-6 overflow-x-auto border-b border-line px-4 [scrollbar-width:none] sm:mx-0 sm:px-0 [&::-webkit-scrollbar]:hidden">
          <ul className="flex min-w-max gap-6">
            {TABS.map((tab) => (
              <li key={tab.to}>
                <NavLink
                  to={tab.to}
                  end={tab.end}
                  className={({ isActive }) =>
                    cn(
                      'relative block whitespace-nowrap pb-3 text-[14.5px] font-medium transition-colors',
                      isActive ? 'text-accent' : 'text-muted hover:text-fg-2',
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      {tab.label}
                      {isActive ? <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent shadow-[0_0_12px_rgb(184_243_107/0.6)]" /> : null}
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <Outlet />
      </div>
    </CvDraftProvider>
  )
}
