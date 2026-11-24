import { ChevronRight, Database, PanelLeftClose, PanelLeftOpen, Unplug } from 'lucide-react'
import { motion } from 'motion/react'
import { Tooltip } from 'radix-ui'
import { NavLink, useNavigate } from 'react-router'
import { Logo } from '@/components/brand/Logo'
import { Button } from '@/components/ui/Button'
import { StatusDot } from '@/components/ui/primitives'
import { useHealth } from '@/hooks/data'
import { cn } from '@/lib/cn'
import { IS_DEV } from '@/lib/env'
import { describeIdentity } from '@/lib/identity'
import { useLiveFeed } from '@/stores/liveFeed'
import { usePreferences } from '@/stores/preferences'
import { useSession } from '@/stores/session'
import { NAV_ITEMS, type NavItem } from './nav'

function NavBadge({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const open = useLiveFeed((s) => s.stream.status === 'open')
  const unread = useLiveFeed((s) => s.unread)
  if (item.badge === 'live') {
    if (unread > 0 && !collapsed) {
      return <span className="ml-auto rounded-full bg-accent/15 px-2 text-[11px] font-semibold text-accent tabular">{unread}</span>
    }
    return open ? <StatusDot pulse className={cn(collapsed ? 'absolute right-3 top-2.5 size-1.5' : 'ml-1')} /> : null
  }
  if (item.badge === 'soon' && !collapsed) {
    return <span className="ml-auto rounded-full bg-accent/90 px-1.5 py-px text-[10px] font-semibold text-accent-ink">Soon</span>
  }
  return null
}

function NavEntry({ item, collapsed, onNavigate }: { item: NavItem; collapsed: boolean; onNavigate?: () => void }) {
  const Icon = item.icon
  const link = (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'group relative flex h-11 items-center gap-3 rounded-xl px-3.5 text-[14.5px] transition-colors',
          collapsed && 'justify-center px-0',
          isActive ? 'text-accent' : 'text-fg-2 hover:bg-elevated/60 hover:text-fg',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive ? (
            <motion.span
              layoutId="nav-active"
              className="absolute inset-0 rounded-xl bg-gradient-to-r from-accent/[0.13] to-accent/[0.04] ring-1 ring-inset ring-accent/10"
              transition={{ type: 'spring', stiffness: 500, damping: 40 }}
            >
              <span className="absolute -left-3 top-1/2 h-7 w-[3px] -translate-y-1/2 rounded-r-full bg-accent shadow-[0_0_12px_rgb(184_243_107/0.8)]" />
            </motion.span>
          ) : null}
          <Icon className="relative size-[20px] shrink-0" strokeWidth={isActive ? 2.1 : 1.8} />
          {collapsed ? null : <span className="relative truncate font-medium">{item.label}</span>}
          <NavBadge item={item} collapsed={collapsed} />
        </>
      )}
    </NavLink>
  )
  if (!collapsed) return link
  return (
    <Tooltip.Root delayDuration={150}>
      <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content side="right" sideOffset={10} className="z-50 rounded-lg border border-line-strong bg-elevated px-2.5 py-1.5 text-xs font-medium text-fg shadow-[var(--shadow-pop)]">
          {item.label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}

/** The slot the reference uses for an upsell shows where the data comes from instead. */
function DataSourceCard() {
  const mode = useSession((s) => s.mode)
  const health = useHealth()
  const navigate = useNavigate()
  const demo = mode === 'demo'
  const reachable = !demo && health.isSuccess
  return (
    <div className="rounded-2xl border border-line bg-gradient-to-b from-[#111a25] to-surface p-4">
      <p className="flex items-center gap-2 text-[13.5px] font-semibold text-fg">
        {demo ? <Database className="size-4 text-amber" /> : reachable ? <StatusDot pulse /> : <Unplug className="size-4 text-danger" />}
        {demo ? 'Demo data' : reachable ? 'Connected to API' : health.isLoading ? 'Checking API…' : 'API unreachable'}
      </p>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
        {demo
          ? 'Sample data in your browser. Nothing here comes from the Sanket API.'
          : reachable
            ? 'Search, matches and the live feed come from the Sanket API.'
            : 'Sanket is not answering right now. Check the connection in Settings.'}
      </p>
      {reachable ? null : (
        <Button variant="primary" size="sm" className="mt-3.5 w-full" onClick={() => navigate('/settings')}>
          Data source settings
          <ChevronRight className="size-4" />
        </Button>
      )}
    </div>
  )
}

function UserRow({ collapsed }: { collapsed: boolean }) {
  const mode = useSession((s) => s.mode)
  const token = useSession((s) => s.token)
  const identity = describeIdentity(mode, token)
  const navigate = useNavigate()
  if (identity.kind === 'none') return null
  return (
    <button
      type="button"
      onClick={() => navigate('/settings')}
      className={cn('flex w-full items-center gap-3 rounded-xl border-t border-line p-2 pt-3 text-left transition-colors hover:bg-elevated/60', collapsed && 'justify-center')}
    >
      <Avatar initials={identity.initials} />
      {collapsed ? null : (
        <>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[14px] font-medium text-fg">{identity.name}</span>
            <span className="block truncate text-[12px] text-muted">{identity.detail}</span>
          </span>
          <ChevronRight className="size-4 text-muted" />
        </>
      )}
    </button>
  )
}

export function Avatar({ initials, className }: { initials: string; className?: string }) {
  return (
    <span className={cn('grid size-10 shrink-0 place-items-center rounded-full bg-gradient-to-br from-[#2a3b55] to-[#18222f] text-[13px] font-semibold text-fg ring-2 ring-line-strong', className)}>
      {initials}
    </span>
  )
}

interface SidebarProps {
  /** In the mobile drawer the sidebar is always expanded and closes on navigation. */
  inDrawer?: boolean
  onNavigate?: () => void
}

export function Sidebar({ inDrawer = false, onNavigate }: SidebarProps) {
  const storedCollapsed = usePreferences((s) => s.sidebarCollapsed)
  const toggle = usePreferences((s) => s.toggleSidebar)
  const collapsed = !inDrawer && storedCollapsed
  return (
    <Tooltip.Provider>
      <motion.nav
        aria-label="Main"
        animate={{ width: inDrawer ? 272 : collapsed ? 80 : 252 }}
        transition={{ type: 'spring', stiffness: 380, damping: 38 }}
        className={cn('flex h-full shrink-0 flex-col bg-sidebar', !inDrawer && 'border-r border-line')}
      >
        <div className={cn('flex h-[88px] items-center px-6', collapsed && 'justify-center px-0')}>
          <NavLink to="/" onClick={onNavigate} aria-label="Sanket home">
            <Logo collapsed={collapsed} />
          </NavLink>
        </div>
        <div className={cn('flex flex-col gap-1.5 px-3', !collapsed && 'pl-3 pr-4')}>
          {NAV_ITEMS.map((item) => (
            <NavEntry key={item.to} item={item} collapsed={collapsed} onNavigate={onNavigate} />
          ))}
        </div>
        <div className="mt-auto flex flex-col gap-3 p-4">
          {collapsed || !IS_DEV ? null : <DataSourceCard />}
          {inDrawer ? null : (
            <button
              type="button"
              onClick={toggle}
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              className={cn('flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13px] text-muted transition-colors hover:bg-elevated/60 hover:text-fg', collapsed && 'justify-center px-0')}
            >
              {collapsed ? <PanelLeftOpen className="size-[18px]" /> : <PanelLeftClose className="size-[18px]" />}
              {collapsed ? null : 'Collapse'}
            </button>
          )}
          <UserRow collapsed={collapsed} />
        </div>
      </motion.nav>
    </Tooltip.Provider>
  )
}
