import { Compass } from 'lucide-react'
import { useNavigate } from 'react-router'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/States'

export default function NotFoundPage() {
  const navigate = useNavigate()
  return (
    <Card className="mx-auto mt-16 max-w-lg items-center gap-0 rounded-[var(--radius-card)] pb-0 pt-8 shadow-[var(--shadow-card)] ring-line">
      <Badge variant="outline" className="border-line-strong tabular text-muted">404</Badge>
      <EmptyState
        className="pb-12 pt-6"
        icon={<Compass />}
        title="This page does not exist"
        description="The link may be old, or the address mistyped."
        action={<Button variant="primary" onClick={() => navigate('/')}>Back to Overview</Button>}
      />
    </Card>
  )
}
