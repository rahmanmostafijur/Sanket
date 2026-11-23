import { CircleX, Inbox, KeyRound, Unplug } from 'lucide-react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { ApiError, errorMessage } from '@/api/client'
import { cn } from '@/lib/cn'
import { Button } from './Button'

interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center px-6 py-12 text-center', className)}>
      <div className="mb-4 grid size-12 place-items-center rounded-2xl border border-line-strong bg-elevated text-muted [&_svg]:size-5">
        {icon ?? <Inbox />}
      </div>
      <p className="text-[15px] font-semibold text-fg">{title}</p>
      {description ? <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-muted">{description}</p> : null}
      {action ? <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div> : null}
    </div>
  )
}

/** Error panel that tells unreachable, unauthorised and other failures apart. */
export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const navigate = useNavigate()
  const apiError = error instanceof ApiError ? error : null
  if (apiError?.isUnauthorized) {
    return (
      <EmptyState
        className={className}
        icon={<KeyRound />}
        title="Authentication required"
        description="Sanket needs a credential. Add an API key or sign-in token in Settings, under Developers."
        action={<Button variant="primary" size="sm" onClick={() => navigate('/settings')}>Add credential</Button>}
      />
    )
  }
  if (apiError?.isUnavailable) {
    return (
      <EmptyState
        className={className}
        icon={<Unplug />}
        title="Sanket is not reachable"
        description="Sanket is not answering right now. Try again in a moment, or check the connection address in Settings."
        action={onRetry ? <Button size="sm" onClick={onRetry}>Try again</Button> : undefined}
      />
    )
  }
  return (
    <EmptyState
      className={className}
      icon={<CircleX />}
      title="Something went wrong"
      description={errorMessage(error)}
      action={onRetry ? <Button size="sm" onClick={onRetry}>Try again</Button> : undefined}
    />
  )
}
