import { Bell, Menu, Zap } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { Popover } from 'radix-ui'
import { useState } from 'react'
import { Link } from 'react-router'
import { SignInButton } from '@/components/auth/GuestPrompt'
import { Button } from '@/components/ui/Button'
import { useIsGuest } from '@/lib/auth'
import { percent, relativeTime } from '@/lib/format'
import { useLiveFeed } from '@/stores/liveFeed'
import { GlobalSearch } from './GlobalSearch'
import { LiveStatusPill } from './LiveStatus'

const POP = {
  initial: { opacity: 0, y: -6, scale: 0.98 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -6, scale: 0.98 },
  transition: { duration: 0.15, ease: [0.22, 1, 0.36, 1] },
} as const

function Notifications() {
  const [open, setOpen] = useState(false)
  const received = useLiveFeed((s) => s.received)
  const unread = useLiveFeed((s) => s.unread)
  const markRead = useLiveFeed((s) => s.markRead)
  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) markRead()
      }}
    >
      <Popover.Trigger asChild>
        <button type="button" aria-label={`Notifications${unread ? `, ${unread} new` : ''}`} className="relative grid size-10 place-items-center rounded-xl text-fg-2 transition-colors hover:bg-elevated hover:text-fg">
          <Bell className="size-[22px]" />
          <AnimatePresence>
            {unread > 0 ? (
              <motion.span
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                exit={{ scale: 0 }}
                className="absolute right-1 top-1 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-[#ff4d5e] px-1 text-[10.5px] font-bold text-white ring-2 ring-bg tabular"
              >
                {unread > 9 ? '9+' : unread}
              </motion.span>
            ) : null}
          </AnimatePresence>
        </button>
      </Popover.Trigger>
      <AnimatePresence>
        {open ? (
          <Popover.Portal forceMount>
            <Popover.Content asChild align="end" sideOffset={10} forceMount>
              <motion.div {...POP} className="z-50 w-[360px] max-w-[calc(100vw-24px)] rounded-2xl border border-line-strong bg-[#111a26] shadow-[var(--shadow-pop)]">
                <div className="border-b border-line px-4 py-3">
                  <p className="text-sm font-semibold text-fg">Notifications</p>
                </div>
                <div className="scroll-thin max-h-[360px] overflow-y-auto p-1.5">
                  {received.length === 0 ? (
                    <p className="px-4 py-8 text-center text-[13px] text-muted">New matches from the live feed appear here.</p>
                  ) : (
                    received.slice(0, 12).map(({ event, receivedAt }) => (
                      <Link
                        key={event.id}
                        to={`/jobs/${event.job_id}`}
                        onClick={() => setOpen(false)}
                        className="flex items-start gap-3 rounded-xl px-3 py-2.5 hover:bg-elevated"
                      >
                        <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-accent/10 text-accent"><Zap className="size-3.5" /></span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13.5px] font-medium text-fg">{event.job?.title ?? `Job ${event.job_id}`}</span>
                          <span className="block text-[12px] text-muted">
                            <span className="text-accent">{percent(event.score)}% match</span> · {relativeTime(new Date(receivedAt).toISOString())}
                          </span>
                        </span>
                      </Link>
                    ))
                  )}
                </div>
                <div className="border-t border-line p-2">
                  <Link to="/live" onClick={() => setOpen(false)} className="block rounded-lg py-2 text-center text-[13px] font-medium text-accent hover:bg-elevated">
                    Open Live Matches
                  </Link>
                </div>
              </motion.div>
            </Popover.Content>
          </Popover.Portal>
        ) : null}
      </AnimatePresence>
    </Popover.Root>
  )
}

export function Topbar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const guest = useIsGuest()
  return (
    <header className="sticky top-0 z-30 border-b border-line/60 bg-bg/80 backdrop-blur-xl lg:border-none lg:bg-bg/70">
      <div className="flex h-[72px] items-center gap-3 px-4 sm:px-6 lg:h-[88px] lg:gap-6 lg:px-10">
        <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation" onClick={onOpenMenu}>
          <Menu className="!size-5" />
        </Button>
        <GlobalSearch className="min-w-0 max-w-[870px] flex-1" />
        <div className="ml-auto flex items-center gap-2 sm:gap-5">
          {guest ? (
            // The live feed and its notifications belong to an account.
            <SignInButton />
          ) : (
            <>
              <LiveStatusPill className="hidden sm:inline-flex" />
              <Notifications />
            </>
          )}
        </div>
      </div>
    </header>
  )
}
