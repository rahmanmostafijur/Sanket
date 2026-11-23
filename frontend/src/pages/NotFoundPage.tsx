import { Compass } from 'lucide-react'
import { useNavigate } from 'react-router'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/States'

export default function NotFoundPage() {
  const navigate = useNavigate()
  return (
    <EmptyState
      className="py-24"
      icon={<Compass />}
      title="This page does not exist"
      description="The link may be old, or the address mistyped."
      action={<Button variant="primary" onClick={() => navigate('/')}>Back to Overview</Button>}
    />
  )
}
