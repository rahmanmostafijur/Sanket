import { Database, RotateCw, Unplug } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { Suspense, useState } from 'react'
import { Link, useLocation, useOutlet } from 'react-router'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { Toaster } from '@/components/ui/Toaster'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useHealth } from '@/hooks/data'
import { IS_DEV } from '@/lib/env'
import { useSession } from '@/stores/session'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

function ConnectionBanner() {
  const mode = useSession((s) => s.mode)
  const baseUrl = useSession((s) => s.apiBaseUrl)
  const health = useHealth()
  if (mode === 'demo') {
    return (
      <div className="mx-4 mt-1 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-amber/25 bg-amber/[0.06] px-4 py-2.5 text-[13px] text-fg-2 sm:mx-6 lg:mx-10">
        <Database className="size-4 shrink-0 text-amber" />
        <span className="min-w-0 flex-1">
          <span className="font-semibold text-amber">Demo data.</span> You are exploring sample listings in your browser. Nothing here comes from Sanket.
        </span>
        {IS_DEV ? <Link to="/settings" className="font-medium text-amber hover:underline">Data source settings</Link> : null}
      </div>
    )
  }
  if (!health.isError) return null
  return (
    <div role="alert" className="mx-4 mt-1 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-danger/30 bg-danger/[0.07] px-4 py-2.5 text-[13px] text-fg-2 sm:mx-6 lg:mx-10">
      <Unplug className="size-4 shrink-0 text-danger" />
      <span className="min-w-0 flex-1">
        <span className="font-semibold text-danger">Can’t reach Sanket</span> at <code className="font-mono text-[12px] text-fg">{baseUrl}</code> right now. Check your connection and try again.
      </span>
      <span className="flex items-center gap-3">
        <button type="button" onClick={() => void health.refetch()} className="inline-flex items-center gap-1 font-medium text-fg hover:underline">
          <RotateCw className="size-3.5" /> Retry
        </button>
      </span>
    </div>
  )
}

function MobileNav({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="left"
        aria-describedby={undefined}
        className="w-auto max-w-none gap-0 border-line bg-sidebar p-0 data-[side=left]:sm:max-w-none lg:hidden"
      >
        <SheetTitle className="sr-only">Navigation</SheetTitle>
        <Sidebar inDrawer onNavigate={() => onOpenChange(false)} />
      </SheetContent>
    </Sheet>
  )
}

function PageFallback() {
  return <div className="flex h-64 items-center justify-center"><span className="size-5 animate-spin rounded-full border-2 border-line-strong border-t-accent" /></div>
}

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()
  const outlet = useOutlet()
  return (
    <TooltipProvider>
    <div className="flex min-h-dvh">
      <div className="sticky top-0 hidden h-dvh lg:block">
        <Sidebar />
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenMenu={() => setMenuOpen(true)} />
        <ConnectionBanner />
        <main id="main" className="relative min-w-0 flex-1 px-4 pb-12 pt-4 sm:px-6 lg:px-10 lg:pt-2">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            >
              <Suspense fallback={<PageFallback />}>{outlet}</Suspense>
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
      <MobileNav open={menuOpen} onOpenChange={setMenuOpen} />
      <Toaster />
    </div>
    </TooltipProvider>
  )
}
