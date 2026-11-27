import {
  Bookmark,
  BriefcaseBusiness,
  Radar,
  Search,
  Settings,
  UserRound,
  type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  badge?: 'live' | 'soon'
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: '/', label: 'Overview', icon: BriefcaseBusiness },
  { to: '/discover', label: 'Discover Jobs', icon: Search },
  { to: '/live', label: 'Live Matches', icon: Radar, badge: 'live' },
  { to: '/saved', label: 'Saved Jobs', icon: Bookmark },
  { to: '/profile', label: 'Profile', icon: UserRound },
  { to: '/settings', label: 'Settings', icon: Settings },
]
