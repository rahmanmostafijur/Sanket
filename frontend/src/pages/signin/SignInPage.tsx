import { LogIn } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation } from 'react-router'
import { logIn } from '@/api/endpoints'
import { AuthCard, FormError } from '@/components/auth/AuthCard'
import { Button } from '@/components/ui/Button'
import { Field, Input } from '@/components/ui/Field'
import { destinationFrom, emailProblem, fromState, SIGN_UP_PATH } from '@/lib/auth'
import { authFailure, type AuthFailure } from '@/lib/authErrors'
import { DEFAULT_API_BASE, useSession } from '@/stores/session'

const NO_FAILURE: AuthFailure = { form: null, email: null, password: null, emailTaken: false }

/** Problems found before anything is sent; a password is only checked for being there. */
function checkInput(email: string, password: string): AuthFailure {
  return { ...NO_FAILURE, email: emailProblem(email), password: password ? null : 'Enter your password.' }
}

export default function SignInPage() {
  const token = useSession((s) => s.token)
  const setToken = useSession((s) => s.setToken)
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [failure, setFailure] = useState<AuthFailure>(NO_FAILURE)
  const [pending, setPending] = useState(false)
  const emailId = useId()
  const passwordId = useId()

  if (token) return <Navigate to={destinationFrom(location.state)} replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (pending) return
    const problems = checkInput(email, password)
    if (problems.email || problems.password) {
      setFailure(problems)
      return
    }
    setFailure(NO_FAILURE)
    setPending(true)
    try {
      const session = await logIn({ baseUrl: DEFAULT_API_BASE, token: null }, { email: email.trim(), password })
      setToken(session.access_token)
    } catch (error: unknown) {
      setFailure(authFailure(error))
      setPending(false)
    }
  }

  return (
    <AuthCard
      title="Sign in to Sanket"
      description="Welcome back. Sign in to see your matches and saved jobs."
      footer={
        <p>
          New to Sanket?{' '}
          <Link to={SIGN_UP_PATH} state={fromState(location.state)} className="font-medium text-accent hover:underline">
            Create an account
          </Link>
        </p>
      }
    >
      <form onSubmit={(event) => void submit(event)} noValidate className="space-y-4">
        <Field label="Email" htmlFor={emailId} error={failure.email}>
          <Input
            id={emailId}
            type="email"
            autoComplete="email"
            inputMode="email"
            spellCheck={false}
            autoFocus
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={failure.email ? true : undefined}
            disabled={pending}
          />
        </Field>
        <Field label="Password" htmlFor={passwordId} error={failure.password}>
          <Input
            id={passwordId}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-invalid={failure.password ? true : undefined}
            disabled={pending}
          />
        </Field>
        {failure.form ? <FormError>{failure.form}</FormError> : null}
        <Button type="submit" variant="primary" size="lg" className="w-full" disabled={pending}>
          <LogIn /> {pending ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </AuthCard>
  )
}
