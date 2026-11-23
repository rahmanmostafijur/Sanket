import { cn } from '@/lib/cn'

/** The Sanket mark: a signal radiating from a point ("sanket" means signal). */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" fill="none" className={cn('size-9', className)} aria-hidden>
      <circle cx="20" cy="20" r="17" stroke="var(--color-accent)" strokeWidth="2.6" strokeLinecap="round" strokeDasharray="80 27" transform="rotate(-50 20 20)" />
      <circle cx="20" cy="20" r="11.5" stroke="var(--color-accent)" strokeWidth="2.6" strokeLinecap="round" strokeDasharray="52 20" transform="rotate(130 20 20)" opacity="0.9" />
      <circle cx="20" cy="20" r="6" stroke="var(--color-accent)" strokeWidth="2.6" opacity="0.85" />
      <circle cx="20" cy="20" r="2.2" fill="var(--color-accent)" />
    </svg>
  )
}

export function Logo({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark className="drop-shadow-[0_0_10px_rgb(184_243_107/0.35)]" />
      {collapsed ? null : (
        <span className="text-[23px] font-semibold tracking-[-0.03em] text-fg">
          Sanket<span className="text-accent">.</span>
        </span>
      )}
    </span>
  )
}
