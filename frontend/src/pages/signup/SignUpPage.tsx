import { UserRoundPlus } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation } from 'react-router'
import { signUp } from '@/api/endpoints'
import { AuthCard, FormError } from '@/components/auth/AuthCard'
import { Button } from '@/components/ui/Button'
import { Field, Input } from '@/components/ui/Field'
import { destinationFrom, emailProblem, fromState, PASSWORD_MIN_LENGTH, passwordProblem, SIGN_IN_PATH } from '@/lib/auth'
import { authFailure } from '@/lib/authErrors'
import { DEFAULT_API_BASE, useSession } from '@/stores/session'

/** A new account starts with no matching profile, so without a page to return to it goes there next. */
const AFTER_SIGN_UP = '/profile'

interface SignUpErrors {
  form: string | null
  email: string | null
  password: string | null
  confirm: string | null
  emailTaken: boolean
}

const NO_ERRORS: SignUpErrors = { form: null, email: null, password: null, confirm: null, emailTaken: false }

function checkInput(email: string, password: string, confirm: string): SignUpErrors {
  const mismatch = confirm !== password ? 'The passwords do not match.' : null
  return {
    ...NO_ERRORS,
    email: emailProblem(email),
    password: passwordProblem(password),
    confirm: confirm ? mismatch : 'Enter the password again.',
  }
}

function hasProblem(errors: SignUpErrors): boolean {
  return Boolean(errors.email || errors.password || errors.confirm)
}

export default function SignUpPage() {
  const token = useSession((s) => s.token)
  const setToken = useSession((s) => s.setToken)
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<SignUpErrors>(NO_ERRORS)
  const [submitted, setSubmitted] = useState(false)
  const [pending, setPending] = useState(false)
  const emailId = useId()
  const passwordId = useId()
  const confirmId = useId()

  if (token) return <Navigate to={destinationFrom(location.state, AFTER_SIGN_UP)} replace />

  // After the first attempt, each field re-checks as the user types so a fixed problem clears at once.
  const recheck = (next: { email?: string; password?: string; confirm?: string }) => {
    if (!submitted) return
    const found = checkInput(next.email ?? email, next.password ?? password, next.confirm ?? confirm)
    // "Already exists" came from the server: it stays until the email itself is edited.
    const keepTaken = next.email === undefined
    setErrors((current) => (keepTaken && current.emailTaken ? { ...found, email: current.email, emailTaken: true } : found))
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (pending) return
    setSubmitted(true)
    const problems = checkInput(email, password, confirm)
    if (hasProblem(problems)) {
      setErrors(problems)
      return
    }
    setErrors(NO_ERRORS)
    setPending(true)
    try {
      const session = await signUp({ baseUrl: DEFAULT_API_BASE, token: null }, { email: email.trim(), password })
      // Signed in straight away: the token is the account's session.
      setToken(session.access_token)
    } catch (error: unknown) {
      setErrors({ ...authFailure(error), confirm: null })
      setPending(false)
    }
  }

  return (
    <AuthCard
      title="Create your account"
      description="Save jobs and get matches scored against your own profile."
      footer={
        <p>
          Already have an account?{' '}
          <Link to={SIGN_IN_PATH} state={fromState(location.state)} className="font-medium text-accent hover:underline">
            Sign in
          </Link>
        </p>
      }
    >
      <form onSubmit={(event) => void submit(event)} noValidate className="space-y-4">
        <Field label="Email" htmlFor={emailId} error={errors.email}>
          <Input
            id={emailId}
            type="email"
            autoComplete="email"
            inputMode="email"
            spellCheck={false}
            autoFocus
            value={email}
            onChange={(event) => {
              setEmail(event.target.value)
              recheck({ email: event.target.value })
            }}
            aria-invalid={errors.email ? true : undefined}
            disabled={pending}
          />
        </Field>
        {errors.emailTaken ? (
          <p className="-mt-2 text-[12.5px] text-muted">
            <Link to={SIGN_IN_PATH} state={fromState(location.state)} className="font-medium text-accent hover:underline">
              Sign in instead
            </Link>
          </p>
        ) : null}
        <Field label="Password" htmlFor={passwordId} error={errors.password} hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}>
          <Input
            id={passwordId}
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value)
              recheck({ password: event.target.value })
            }}
            aria-invalid={errors.password ? true : undefined}
            disabled={pending}
          />
        </Field>
        <Field label="Confirm password" htmlFor={confirmId} error={errors.confirm}>
          <Input
            id={confirmId}
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => {
              setConfirm(event.target.value)
              recheck({ confirm: event.target.value })
            }}
            aria-invalid={errors.confirm ? true : undefined}
            disabled={pending}
          />
        </Field>
        {errors.form ? <FormError>{errors.form}</FormError> : null}
        <Button type="submit" variant="primary" size="lg" className="w-full" disabled={pending}>
          <UserRoundPlus /> {pending ? 'Creating account…' : 'Create account'}
        </Button>
      </form>
    </AuthCard>
  )
}
