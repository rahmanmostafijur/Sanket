import { LogIn } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router'
import { ApiError, errorMessage } from '@/api/client'
import { listProfiles } from '@/api/endpoints'
import { Logo } from '@/components/brand/Logo'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/Field'
import { DEFAULT_API_BASE, useSession } from '@/stores/session'

const SIGN_IN_PATH = '/signin'
const EMPTY_MESSAGE = 'Enter your access key or token.'
const REFUSED_MESSAGE = 'That key or token was not accepted.'
const NO_ACCESS_MESSAGE = 'This credential is valid but does not have access.'

/** Where the user was heading before being sent here: only an in-app path, never the sign-in page. */
function destinationFrom(state: unknown): string {
  const from = typeof state === 'object' && state !== null && 'from' in state ? (state as { from: unknown }).from : null
  if (typeof from !== 'object' || from === null) return '/'
  const { pathname, search, hash } = from as { pathname?: unknown; search?: unknown; hash?: unknown }
  if (typeof pathname !== 'string' || !pathname.startsWith('/') || pathname.startsWith('//') || pathname === SIGN_IN_PATH) return '/'
  return `${pathname}${typeof search === 'string' ? search : ''}${typeof hash === 'string' ? hash : ''}`
}

function verifyFailure(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return REFUSED_MESSAGE
  if (error instanceof ApiError && error.status === 403) return NO_ACCESS_MESSAGE
  return errorMessage(error)
}

export default function SignInPage() {
  const token = useSession((s) => s.token)
  const setToken = useSession((s) => s.setToken)
  const location = useLocation()
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const inputId = useId()
  const helpId = useId()
  const destination = destinationFrom(location.state)

  if (token) return <Navigate to={destination} replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (pending) return
    const candidate = draft.trim()
    if (!candidate) {
      setError(EMPTY_MESSAGE)
      return
    }
    setError(null)
    setPending(true)
    try {
      await listProfiles({ baseUrl: DEFAULT_API_BASE, token: candidate })
    } catch (failure: unknown) {
      setError(verifyFailure(failure))
      setPending(false)
      return
    }
    setToken(candidate)
  }

  return (
    <main className="grid min-h-dvh place-items-center bg-bg px-4 py-10">
      <Card className="w-full max-w-sm gap-6 [--card-spacing:--spacing(6)]">
        <CardHeader className="justify-items-center gap-4 text-center">
          <Logo />
          <CardTitle className="text-xl font-semibold text-fg">Sign in to Sanket</CardTitle>
          <CardDescription className="text-muted">Use the access key or token for your Sanket service.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={(event) => void submit(event)} noValidate className="space-y-4">
            <Field label="Access key or token" htmlFor={inputId} error={error}>
              <Input
                id={inputId}
                type="password"
                autoComplete="off"
                spellCheck={false}
                autoFocus
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                aria-invalid={error ? true : undefined}
                aria-describedby={helpId}
                disabled={pending}
                className="font-mono text-[13px]"
              />
            </Field>
            <p id={helpId} className="text-[12.5px] leading-relaxed text-subtle">
              Your key or token is given to you by whoever runs your Sanket service. It is kept only for this browser session.
            </p>
            <Button type="submit" variant="primary" size="lg" className="w-full" disabled={pending}>
              <LogIn /> {pending ? 'Checking…' : 'Sign in'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  )
}
