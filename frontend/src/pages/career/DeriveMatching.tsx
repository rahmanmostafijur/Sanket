import { LoaderCircle, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { useDeriveMatching } from './useDeriveMatching'

/** The button that starts a matching profile from the career profile, with its progress and any refusal. */
export function DeriveMatching({ variant = 'primary' }: { variant?: 'primary' | 'outline' }) {
  const derive = useDeriveMatching()
  return (
    <div className="space-y-3">
      <Button variant={variant} disabled={derive.pending} onClick={derive.run}>
        {derive.pending ? <LoaderCircle className="animate-spin" /> : <Sparkles />} Create matching profile from my career profile
      </Button>
      {derive.pending ? <p role="status" className="text-[13px] text-muted">Reading your career profile...</p> : null}
      {derive.error ? <p role="alert" className="text-[13px] text-danger">{derive.error}</p> : null}
    </div>
  )
}
