import { Check, Copy, Eye, EyeOff, Info, KeyRound, LogOut, PlugZap, Server, ShieldCheck } from 'lucide-react'
import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { getHealth } from '@/api/endpoints'
import { errorMessage } from '@/api/client'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { Field, Input } from '@/components/ui/Field'
import { Card, StatusDot } from '@/components/ui/primitives'
import { useNow } from '@/hooks/useNow'
import { cn } from '@/lib/cn'
import { describeIdentity, jwtExpiry } from '@/lib/identity'
import { DEFAULT_API_BASE, useSession } from '@/stores/session'
import { toast } from '@/stores/toasts'

const ENDPOINTS: [string, string, string][] = [
  ['GET', '/search', 'Job search: hybrid, keyword or semantic, with filters and sort'],
  ['GET', '/jobs', 'Browse listed jobs without a query'],
  ['GET', '/jobs/{job_id}', 'One job with its description and every listing'],
  ['GET', '/saved-jobs', 'Your saved jobs, newest first'],
  ['PUT', '/saved-jobs/{job_id}', 'Save a job'],
  ['DELETE', '/saved-jobs/{job_id}', 'Remove a saved job'],
  ['GET', '/profiles', 'Your matching profiles'],
  ['POST', '/profiles', 'Create a profile'],
  ['PUT', '/profiles/{id}', 'Replace a profile'],
  ['DELETE', '/profiles/{id}', 'Delete a profile and its matches'],
  ['GET', '/profiles/{id}/matches', 'Matches of a profile, paged by id'],
  ['GET', '/profiles/{id}/matches/stream', 'Live matches (Server-Sent Events)'],
  ['POST', '/auth/stream-token', 'Short-lived token for opening the stream'],
  ['GET', '/healthz', 'Liveness'],
]

const METHOD_STYLE: Record<string, string> = {
  GET: 'text-info bg-info/10',
  POST: 'text-accent bg-accent/10',
  PUT: 'text-amber bg-amber/10',
  DELETE: 'text-danger bg-danger/10',
}

function mask(token: string): string {
  if (token.length <= 10) return '•'.repeat(token.length)
  return `${token.slice(0, 4)}${'•'.repeat(Math.min(24, token.length - 8))}${token.slice(-4)}`
}

function useCopy(): [boolean, (text: string) => void] {
  const [copied, setCopied] = useState(false)
  const copy = (text: string) => {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1600)
      })
      .catch(() => toast({ tone: 'error', title: 'Could not copy', description: 'Your browser blocked clipboard access.' }))
  }
  return [copied, copy]
}

function Panel({ icon, title, description, children }: { icon: ReactNode; title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex items-start gap-3.5">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl border border-line-strong bg-elevated text-accent [&_svg]:size-5">{icon}</span>
        <div className="min-w-0">
          <h2 className="text-[16px] font-semibold text-fg">{title}</h2>
          {description ? <p className="mt-1 text-[13.5px] leading-relaxed text-muted">{description}</p> : null}
        </div>
      </div>
      <div className="mt-5">{children}</div>
    </Card>
  )
}

function ConnectionPanel() {
  const { apiBaseUrl, setApiBaseUrl, mode, setMode, token } = useSession()
  const [draft, setDraft] = useState(apiBaseUrl)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)
  const [testing, setTesting] = useState(false)
  const inputId = useId()
  const test = async (event: FormEvent) => {
    event.preventDefault()
    setTesting(true)
    const started = performance.now()
    try {
      await getHealth({ baseUrl: draft.trim() || DEFAULT_API_BASE, token })
      setApiBaseUrl(draft)
      setResult({ ok: true, text: `Reachable in ${Math.round(performance.now() - started)} ms. Address saved.` })
    } catch (failure: unknown) {
      setResult({ ok: false, text: errorMessage(failure) })
    } finally {
      setTesting(false)
    }
  }
  return (
    <Panel icon={<Server />} title="Connection" description="Where this app reaches the Sanket API. In development the Vite proxy serves it at /api.">
      <form onSubmit={test} className="space-y-4">
        <Field label="API address" htmlFor={inputId} hint="A path on this site (/api) or a full URL on the same origin; the API sends no CORS headers.">
          <div className="flex gap-2">
            <Input id={inputId} value={draft} onChange={(e) => setDraft(e.target.value)} className="font-mono text-[13px]" spellCheck={false} />
            <Button type="submit" disabled={testing}><PlugZap /> {testing ? 'Testing…' : 'Test & save'}</Button>
          </div>
        </Field>
        {result ? <p className={cn('text-[13px]', result.ok ? 'text-accent' : 'text-danger')}>{result.text}</p> : null}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-bg/40 px-4 py-3">
          <span className="flex items-center gap-2 text-[13.5px] text-fg-2">
            <StatusDot tone={mode === 'demo' ? 'amber' : 'accent'} />
            {mode === 'demo' ? 'Showing demo data, not the API' : 'Reading from the Sanket API'}
          </span>
          <Button size="sm" variant="outline" onClick={() => setMode(mode === 'demo' ? 'api' : 'demo')}>
            {mode === 'demo' ? 'Use the API' : 'Switch to demo data'}
          </Button>
        </div>
      </form>
    </Panel>
  )
}

function CredentialPanel() {
  const { token, rememberToken, setToken, clearToken } = useSession()
  const [draft, setDraft] = useState('')
  const [remember, setRemember] = useState(false)
  const [reveal, setReveal] = useState(false)
  const [copied, copy] = useCopy()
  const inputId = useId()
  const identity = describeIdentity('api', token)
  const now = useNow()
  const expiry = token ? jwtExpiry(token) : null
  const expired = expiry !== null && expiry.getTime() < now
  const save = (event: FormEvent) => {
    event.preventDefault()
    if (!draft.trim()) return
    setToken(draft, remember)
    setDraft('')
    toast({ tone: 'success', title: 'Credential saved', description: remember ? 'Remembered on this device.' : 'Kept for this browser tab only.' })
  }
  return (
    <Panel icon={<KeyRound />} title="Credential" description="Requests are sent with this API key or JWT as a Bearer token. It never leaves this browser except to the Sanket API.">
      {token ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2 rounded-xl border border-line bg-bg/40 py-2 pl-4 pr-2">
            <code className="min-w-0 flex-1 truncate font-mono text-[13px] text-fg-2">{reveal ? token : mask(token)}</code>
            <Button size="icon-sm" variant="ghost" aria-label={reveal ? 'Hide credential' : 'Show credential'} onClick={() => setReveal((v) => !v)}>{reveal ? <EyeOff /> : <Eye />}</Button>
            <Button size="icon-sm" variant="ghost" aria-label="Copy credential" onClick={() => copy(token)}>{copied ? <Check className="text-accent" /> : <Copy />}</Button>
          </div>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-[13px] sm:grid-cols-3">
            <div><dt className="text-subtle">Type</dt><dd className="text-fg-2">{identity.kind === 'jwt' ? 'JWT' : 'API key'}</dd></div>
            <div><dt className="text-subtle">Stored</dt><dd className="text-fg-2">{rememberToken ? 'On this device' : 'This tab only'}</dd></div>
            <div><dt className="text-subtle">Expires</dt><dd className={cn(expired ? 'text-danger' : 'text-fg-2')}>{expiry ? (expired ? 'Expired' : expiry.toLocaleString()) : 'Not stated'}</dd></div>
          </dl>
          <Button variant="danger" size="sm" onClick={clearToken}><LogOut /> Forget credential</Button>
        </div>
      ) : null}
      <form onSubmit={save} className={cn('space-y-3', token && 'mt-6 border-t border-line pt-5')}>
        <Field label={token ? 'Replace credential' : 'API key or JWT'} htmlFor={inputId}>
          <Input id={inputId} type="password" autoComplete="off" spellCheck={false} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Paste your key or token" className="font-mono text-[13px]" />
        </Field>
        <label className="flex items-center gap-2.5 text-[13.5px] text-fg-2">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="size-4 accent-[var(--color-accent)]" />
          Remember on this device
        </label>
        <p className="text-[12.5px] text-subtle">Only remember a credential on a device you trust; anything stored in the browser can be read by scripts on this site.</p>
        <Button type="submit" variant="primary" disabled={!draft.trim()}><ShieldCheck /> Save credential</Button>
      </form>
    </Panel>
  )
}

function KeysPanel() {
  return (
    <Panel icon={<ShieldCheck />} title="API keys" description="How access to Sanket is granted.">
      <div className="space-y-3 text-[13.5px] leading-relaxed text-fg-2">
        <p>API keys are issued by whoever runs your Sanket server (the <code className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[12px]">AUTH_API_KEYS</code> setting), and JWTs come from its identity provider.</p>
        <p className="flex gap-2 rounded-xl border border-line bg-bg/40 p-3.5 text-[13px] text-muted">
          <Info className="mt-0.5 size-4 shrink-0 text-info" />
          This version of the API has no endpoints to create, revoke or meter keys, so key generation and usage statistics are not shown here. Ask your Sanket operator for a key or to revoke one.
        </p>
      </div>
    </Panel>
  )
}

function EndpointsPanel() {
  const baseUrl = useSession((s) => s.apiBaseUrl)
  const [copied, copy] = useCopy()
  const example = `curl -H "Authorization: Bearer $SANKET_TOKEN" \\\n  "${baseUrl.startsWith('http') ? baseUrl : `http://127.0.0.1:8000`}/search?q=python+backend&work_mode=remote"`
  return (
    <Panel icon={<PlugZap />} title="Endpoints" description="The API surface this app uses. Every result links to its original listing and names its source.">
      <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line">
        {ENDPOINTS.map(([method, path, text]) => (
          <li key={`${method} ${path}`} className="flex flex-wrap items-center gap-3 bg-bg/30 px-4 py-2.5">
            <span className={cn('w-16 rounded-md py-0.5 text-center font-mono text-[11px] font-semibold', METHOD_STYLE[method])}>{method}</span>
            <code className="font-mono text-[12.5px] text-fg">{path}</code>
            <span className="ml-auto text-[12.5px] text-muted">{text}</span>
          </li>
        ))}
      </ul>
      <div className="relative mt-4">
        <pre className="scroll-thin overflow-x-auto rounded-xl border border-line bg-[#070b12] p-4 pr-12 font-mono text-[12.5px] leading-relaxed text-fg-2">{example}</pre>
        <Button size="icon-sm" variant="ghost" aria-label="Copy example" className="absolute right-2 top-2" onClick={() => copy(example)}>{copied ? <Check className="text-accent" /> : <Copy />}</Button>
      </div>
      <p className="mt-2 text-[12px] text-subtle">Set SANKET_TOKEN in your shell; the example never contains your credential.</p>
    </Panel>
  )
}

export default function IntegrationsPage() {
  return (
    <div className="mx-auto max-w-[980px]">
      <PageHeader title="API & Integrations" description="Connect this app to your Sanket API and manage how it authenticates." />
      <div className="space-y-5">
        <ConnectionPanel />
        <CredentialPanel />
        <KeysPanel />
        <EndpointsPanel />
      </div>
    </div>
  )
}
