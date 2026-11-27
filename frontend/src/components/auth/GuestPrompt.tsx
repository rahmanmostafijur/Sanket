import { LogIn, UserRoundPlus } from 'lucide-react'
import { Button, type ButtonProps } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/States'
import { useAuthNavigation } from '@/hooks/useAuthNavigation'
import { cn } from '@/lib/cn'

/** The "Sign in" button guests see in the top bar and the sidebar. */
export function SignInButton({ className, size = 'md', compact = false }: { className?: string; size?: ButtonProps['size']; compact?: boolean }) {
  const { signIn } = useAuthNavigation()
  return (
    <Button variant="primary" size={size} className={className} onClick={signIn} aria-label={compact ? 'Sign in' : undefined}>
      <LogIn /> {compact ? null : 'Sign in'}
    </Button>
  )
}

const GUEST_PROMPT_TITLE = 'Create a profile to get matches'

interface GuestPromptProps {
  description?: string
  className?: string
  /** `banner` is one compact row for the top of a page; `panel` fills the space personal content would take. */
  variant?: 'panel' | 'banner'
}

/** Shown to guests where personal features (matches, saved jobs, the live feed) would be. */
export function GuestPrompt({ description, className, variant = 'panel' }: GuestPromptProps) {
  const { signIn, signUp } = useAuthNavigation()
  if (variant === 'banner') {
    return (
      <section
        aria-label={GUEST_PROMPT_TITLE}
        className={cn('flex flex-col gap-4 rounded-[14px] border border-accent/20 bg-accent/[0.04] px-5 py-4 sm:flex-row sm:items-center', className)}
      >
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent [&_svg]:size-5"><UserRoundPlus /></span>
        <div className="min-w-0 flex-1">
          <p className="text-[15px] font-semibold text-fg">{GUEST_PROMPT_TITLE}</p>
          {description ? <p className="mt-0.5 text-[13.5px] leading-relaxed text-muted">{description}</p> : null}
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="primary" size="sm" onClick={signUp}>Create account</Button>
          <Button size="sm" onClick={signIn}>Sign in</Button>
        </div>
      </section>
    )
  }
  return (
    <EmptyState
      className={cn('rounded-[14px] border border-line bg-surface', className)}
      icon={<UserRoundPlus />}
      title={GUEST_PROMPT_TITLE}
      description={
        description ??
        'Create a free account and tell Sanket the roles and skills you want. Jobs are then scored against your profile and new matches arrive live.'
      }
      action={
        <>
          <Button variant="primary" onClick={signUp}>Create account</Button>
          <Button onClick={signIn}>Sign in</Button>
        </>
      }
    />
  )
}
