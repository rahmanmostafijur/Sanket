import { UserRoundX } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { Career } from '@/api/types'
import { Card, Skeleton } from '@/components/ui/primitives'
import { EmptyState, ErrorState } from '@/components/ui/States'
import { useCareer } from '@/hooks/career'
import { isNotFound } from '@/hooks/data'

/** Loads the career profile and shows what the page should show while it is not there to use. */
export function CareerGate({ children }: { children: (career: Career) => ReactNode }) {
  const query = useCareer()
  if (query.isError) {
    if (isNotFound(query.error)) {
      return (
        <Card>
          <EmptyState
            icon={<UserRoundX />}
            title="No career profile for this sign-in"
            description="This credential is not an account, so it has no career profile. Sign in with your account to use it. Your matching profiles still work."
            action={<Link to="/profile/matching" className="text-[13.5px] font-medium text-accent hover:underline">Go to matching profiles</Link>}
          />
        </Card>
      )
    }
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} className="py-16" />
  }
  if (!query.data) {
    return (
      <div className="space-y-4" aria-busy="true">
        <Skeleton className="h-28 rounded-[14px]" />
        <Skeleton className="h-64 rounded-[14px]" />
      </div>
    )
  }
  return <>{children(query.data)}</>
}
