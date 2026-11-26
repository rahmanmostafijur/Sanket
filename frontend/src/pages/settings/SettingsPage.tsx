import { LayoutGrid, List, Trash } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { errorMessage } from '@/api/client'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { SwitchRow } from '@/components/ui/Field'
import { Card } from '@/components/ui/primitives'
import { Segmented } from '@/components/ui/Tabs'
import { useClearSaved, useSavedJobs } from '@/hooks/data'
import { IS_DEV } from '@/lib/env'
import { usePreferences, type ResultsView } from '@/stores/preferences'
import { useSession } from '@/stores/session'
import { toast } from '@/stores/toasts'
import { DevelopersSection } from './DevelopersSection'

const LOCAL_KEYS = ['sanket.session', 'sanket.saved', 'sanket.prefs']
const SESSION_KEYS = ['sanket.token', 'sanket.jobs']

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Card className="p-5 sm:p-6">
      <h2 className="text-[16px] font-semibold text-fg">{title}</h2>
      {description ? <p className="mt-1 text-[13.5px] text-muted">{description}</p> : null}
      <div className="mt-3 divide-y divide-line">{children}</div>
    </Card>
  )
}

function Row({ label, description, children }: { label: string; description?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 py-3.5">
      <div className="min-w-0">
        <p className="text-[14px] font-medium text-fg">{label}</p>
        {description ? <p className="mt-0.5 text-[13px] text-muted">{description}</p> : null}
      </div>
      {children}
    </div>
  )
}

function resetLocalData(): void {
  try {
    for (const key of LOCAL_KEYS) window.localStorage.removeItem(key)
    for (const key of SESSION_KEYS) window.sessionStorage.removeItem(key)
  } catch {
    // Storage blocked: nothing was stored to begin with.
  }
  window.location.assign('/')
}

export default function SettingsPage() {
  const { token, clearToken, rememberToken } = useSession()
  const prefs = usePreferences()
  const savedCount = useSavedJobs().entries.length
  const clearSaved = useClearSaved()
  const [confirmReset, setConfirmReset] = useState(false)

  return (
    <div className="mx-auto max-w-[900px]">
      <PageHeader title="Settings" description={IS_DEV ? 'Preferences, notifications, the data this browser keeps and developer access.' : 'Preferences, notifications and the data this browser keeps.'} />
      <div className="space-y-5">
        <Section title="Preferences">
          <Row label="Default job view">
            <Segmented<ResultsView>
              id="settings-view"
              value={prefs.view}
              onChange={prefs.setView}
              items={[{ value: 'list', label: 'List', icon: <List /> }, { value: 'grid', label: 'Grid', icon: <LayoutGrid /> }]}
            />
          </Row>
          <SwitchRow checked={prefs.sidebarCollapsed} onCheckedChange={() => prefs.toggleSidebar()} label="Compact sidebar" description="Show only icons in the navigation on large screens." />
          <SwitchRow
            checked={prefs.motion === 'reduced'}
            onCheckedChange={(on) => prefs.setMotion(on ? 'reduced' : 'system')}
            label="Reduce motion"
            description="Turn off animations. When off, Sanket follows your system setting."
          />
        </Section>

        <Section title="Notifications">
          <SwitchRow checked={prefs.notifyOnMatch} onCheckedChange={prefs.setNotifyOnMatch} label="New match alerts" description="Show a notification when the live feed delivers a new match. Matches always appear in Live Matches and the bell." />
        </Section>

        <Section title="Security and privacy" description="What this browser stores. Nothing here is sent anywhere except the Sanket API.">
          {IS_DEV ? (
            <Row label="Credential" description={token ? (rememberToken ? 'Remembered on this device.' : 'Kept for this tab only.') : 'None stored.'}>
              <Button size="sm" variant="outline" disabled={!token} onClick={clearToken}>Forget</Button>
            </Row>
          ) : null}
          <Row label="Recent searches" description={`${prefs.recentSearches.length} kept for suggestions.`}>
            <Button size="sm" variant="outline" disabled={!prefs.recentSearches.length} onClick={prefs.clearRecentSearches}>Clear</Button>
          </Row>
          <Row label="Saved jobs" description={`${savedCount} saved.`}>
            <Button
              size="sm"
              variant="outline"
              disabled={!savedCount}
              onClick={() => clearSaved().then(() => toast({ title: 'Saved jobs cleared' }), (error: unknown) => toast({ tone: 'error', title: 'Could not clear every saved job', description: errorMessage(error) }))}
            >
              Clear
            </Button>
          </Row>
          <Row label="Reset this browser" description="Removes the credential, saved jobs, preferences and cached jobs, then reloads.">
            <Button size="sm" variant="danger" onClick={() => setConfirmReset(true)}>Reset</Button>
            <ConfirmDialog
              open={confirmReset}
              onOpenChange={setConfirmReset}
              title="Reset this browser?"
              description="Removes the credential, saved jobs, preferences and cached jobs, then reloads."
              cancelLabel="Cancel"
              confirmLabel={<><Trash /> Reset everything</>}
              onConfirm={resetLocalData}
            />
          </Row>
        </Section>

        {IS_DEV ? <DevelopersSection /> : null}
      </div>
    </div>
  )
}
